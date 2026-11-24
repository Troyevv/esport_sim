import { test, expect, type Locator, type Page, type WebSocketRoute } from '@playwright/test';
import { copyFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

async function connected(page: Page) {
  await expect(page.getByTestId('connection')).toHaveText(/На связи/i);
  await expect(page.getByTestId('radar')).toHaveAttribute('data-ready', 'true');
}

function button(page: Page, name: string) {
  return page.getByRole('button', { name, exact: true });
}

async function activate(locator: Locator, touch: boolean) {
  if (touch) await locator.tap();
  else await locator.click();
}

async function changeSeed(page: Page, value: number, touch: boolean) {
  await page.getByLabel('Seed', { exact: true }).fill(String(value));
  await activate(button(page, 'Сбросить'), touch);
  await expect(page.getByTestId('current-seed')).toHaveText(String(value));
  await expect(page.getByTestId('tick')).toHaveText('0');
}

async function touchCamera(page: Page) {
  const radar = page.getByTestId('radar');
  const canvas = radar.locator('canvas');
  await canvas.scrollIntoViewIfNeeded();
  const rect = await canvas.boundingBox();
  if (!rect) throw new Error('Радар не отображается');
  const x = rect.x + rect.width / 2;
  const y = rect.y + rect.height / 2;
  const cdp = await page.context().newCDPSession(page);
  const dispatch = (
    type: 'touchStart' | 'touchMove' | 'touchEnd',
    points: Array<[number, number]>,
  ) => cdp.send('Input.dispatchTouchEvent', {
    type,
    touchPoints: points.map(([x, y], id) => ({ x, y, id })),
  });

  const initialZoom = Number(await radar.getAttribute('data-zoom'));
  await dispatch('touchStart', [[x - 24, y], [x + 24, y]]);
  await dispatch('touchMove', [[x - 49, y], [x + 49, y]]);
  await dispatch('touchEnd', []);
  await expect.poll(async () => Number(await radar.getAttribute('data-zoom')))
    .toBeGreaterThan(initialZoom);

  const initialPan = await radar.getAttribute('data-pan-x');
  await dispatch('touchStart', [[x, y]]);
  await dispatch('touchMove', [[x + 48, y + 20]]);
  await dispatch('touchEnd', []);
  await expect(radar).not.toHaveAttribute('data-pan-x', initialPan!);
  await cdp.detach();
}

test('управление стендом, общий снимок, жесты и компоновка', async ({page, hasTouch}, testInfo) => {
  const touch = Boolean(hasTouch);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await connected(page);
  await changeSeed(page, 1704, touch);

  const roster = page.locator('section').filter({has: page.getByRole('heading', { name: 'Участники' })});
  await expect(roster.getByRole('button')).toHaveCount(10);
  const projection = page.getByLabel('Режим обзора');
  for (const side of ['T', 'CT', 'full']) {
    await projection.selectOption(side);
    await expect(projection).toHaveValue(side);
    await connected(page);
    await expect(roster.getByRole('button')).toHaveCount(side === 'full' ? 10 : 5);
  }

  await activate(button(page, '4×'), touch);
  await activate(button(page, 'Запустить'), touch);
  await expect.poll(async () => Number(await page.getByTestId('tick').innerText())).toBeGreaterThan(55);
  await activate(button(page, 'Пауза'), touch);
  await expect(button(page, 'Запустить')).toBeEnabled();
  const tick = await page.getByTestId('tick').innerText();
  await activate(button(page, 'Сохранить'), touch);
  await expect(button(page, 'Загрузить')).toBeEnabled();
  await changeSeed(page, 817, touch);
  await activate(button(page, 'Загрузить'), touch);
  await expect(page.getByTestId('current-seed')).toHaveText('1704');
  await expect(page.getByTestId('tick')).toHaveText(tick);

  await activate(button(page, '1×'), touch);
  await expect(button(page, '1×')).toHaveAttribute('aria-pressed', 'true');
  const participant = roster.getByRole('button', {name: /Atlas/});
  await activate(participant, touch);
  await expect(participant).toHaveAttribute('aria-pressed', 'true');
  await expect(roster.getByText(/Известные позиции/)).toBeVisible();
  const radar = page.getByTestId('radar');
  if (touch) {
    await touchCamera(page);
  } else {
    const zoom = Number(await radar.getAttribute('data-zoom'));
    await button(page, 'Увеличить карту').click();
    await expect.poll(async () => Number(await radar.getAttribute('data-zoom'))).toBeGreaterThan(zoom);
  }
  await activate(button(page, 'Центрировать карту'), touch);
  await expect(radar).toHaveAttribute('data-zoom', '1.000');
  await expect(radar).toHaveAttribute('data-pan-x', '0.00');
  await expect(radar).toHaveAttribute('data-pan-y', '0.00');
  if (touch) {
    await activate(button(page, 'Увеличить карту'), true);
    await expect(radar).toHaveAttribute('data-zoom', '1.250');
    await activate(button(page, 'Уменьшить карту'), true);
    await expect(radar).toHaveAttribute('data-zoom', '1.000');
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth
  )).toBeLessThanOrEqual(1);
  await expect(radar).toHaveAttribute('data-ready', 'true');
  await page.evaluate(() => document.fonts.ready);
  const path = testInfo.outputPath(testInfo.project.name + '.png');
  await page.screenshot({path, animations: 'disabled'});
  const fullPage = testInfo.outputPath(testInfo.project.name + '-full.png');
  await page.screenshot({path: fullPage, fullPage: true, animations: 'disabled'});
  await testInfo.attach('Вся страница', {path: fullPage, contentType: 'image/png'});
  await testInfo.attach(testInfo.project.name, {path, contentType: 'image/png'});
  if (process.env.R0_SCREENSHOTS === '1') {
    const dest = fileURLToPath(new URL('../../docs/screenshots/', import.meta.url));
    await mkdir(dest, {recursive: true});
    await copyFile(path, join(dest, testInfo.project.name + '.png'));
  }
  expect(errors).toEqual([]);
});

test('после обрыва WebSocket клиент принимает состояние второго устройства', {tag:'@reconnect'}, async ({page, browser}, testInfo) => {
  let online = true;
  let connection: WebSocketRoute | undefined;
  await page.routeWebSocket('**/api/stream**', socket => {
    if (!online) {
      socket.close({code: 1012, reason: 'Отключение тестового маршрута'});
      return;
    }
    connection = socket;
    socket.connectToServer();
  });
  await page.goto('/');
  await connected(page);
  const desktop = await browser.newContext({baseURL: testInfo.project.use.baseURL});
  const peer = await desktop.newPage();
  try {
    await peer.goto('/');
    await connected(peer);
    online = false;
    connection!.close({code: 1012, reason: 'Обрыв тестового маршрута'});
    await expect(page.getByTestId('connection')).not.toHaveText(/На связи/i);
    await expect(button(page, 'Сбросить')).toBeDisabled();
    await changeSeed(peer, 24680, false);
    online = true;
    await connected(page);
    await expect(page.getByTestId('current-seed')).toHaveText('24680');
    await expect(page.getByTestId('tick')).toHaveText('0');
    const canvas = page.getByTestId('radar').locator('canvas');
    const portraitWidth = (await canvas.boundingBox())!.width;
    await page.setViewportSize({ width: 844, height: 390 });
    await expect.poll(async () => (await canvas.boundingBox())!.width).toBeGreaterThan(portraitWidth);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(async () => (await canvas.boundingBox())!.width).toBe(portraitWidth);
    await expect(page.getByTestId('current-seed')).toHaveText('24680');
  } finally {
    await desktop.close();
  }
});

test('неопределённый результат команды сверяется после потери запроса или ответа', {tag:'@receipts'}, async ({page}) => {
  await page.goto('/');
  await connected(page);
  for (const commitBeforeLoss of [false, true]) {
    const before = await (await page.request.get('/api/state')).json();
    let id: string | undefined;
    await page.route('**/api/command', async route => {
      id = route.request().postDataJSON().id;
      if (commitBeforeLoss) {
        const committed = await route.fetch();
        expect(committed.ok()).toBeTruthy();
      }
      await route.abort('connectionreset');
    }, {times: 1});
    await button(page, 'Сохранить').click();
    await expect(page.getByRole('status').filter({hasText: 'Снимок сохранён'})).toBeVisible();
    await connected(page);
    const receipt = await page.request.get('/api/command/' + id);
    expect(receipt.ok()).toBeTruthy();
    const after = await (await page.request.get('/api/state')).json();
    expect(after.revision).toBe(before.revision + 1);
    expect(await receipt.json()).toEqual({context: after.context, revision: after.revision});
    expect(after.hasSave).toBeTruthy();
  }
});
