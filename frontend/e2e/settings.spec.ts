import { test, expect, type Page } from '@playwright/test';
import { X509Certificate } from 'node:crypto';
import { request as httpsRequest } from 'node:https';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

async function verifyLauncher(page: Page) {
  const temp = await mkdtemp(join(tmpdir(), 'esport-launcher-ui-'));
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const script = 'from backend.desktop import launch; from pathlib import Path; import sys; launch(Path(sys.argv[1]), lambda url: print(url, flush=True))';
  const launcher = spawn(process.env.PYTHON || 'python', ['-c', script, temp], {cwd:root, stdio:['ignore','pipe','inherit']});
  const exit = once(launcher, 'exit');
  let url = '';
  launcher.stdout.setEncoding('utf8').on('data', chunk => {url += chunk;});
  try {
    await expect.poll(() => url.trim()).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/$/);
    await page.goto(url.trim());
    await page.getByRole('button', {name:'Настройки сервера'}).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', {name:'Остановить приложение'}).click();
    await dialog.getByRole('button', {name:'Отмена'}).click();
    await expect(dialog.getByRole('button', {name:'Подтвердить остановку'})).toHaveCount(0);
    await dialog.getByRole('button', {name:'Остановить приложение'}).click();
    await dialog.getByRole('button', {name:'Подтвердить остановку'}).click();
    await expect(dialog.getByRole('status')).toContainText('Завершается работа');
    expect((await exit)[0]).toBe(0);
  } finally {
    if (launcher.exitCode === null && launcher.signalCode === null) launcher.kill();
    await exit;
    await rm(temp, {recursive:true, force:true});
  }
}

test('управление доступом по LAN с домашнего ПК', async ({ page }, testInfo) => {
  const start = page.getByRole('button', {name: 'Настройки сервера'});
  await page.goto('/');
  await start.click();
  const panel = page.getByRole('dialog', {name: 'Домашний сервер'});
  await expect(panel.getByText('Только этот ПК')).toBeVisible();
  await expect(panel.getByRole('button', {name:'Остановить приложение'})).toHaveCount(0);
  const address = panel.getByLabel('Сетевой интерфейс');
  const addresses = await address.locator('option').allTextContents();
  expect(addresses).not.toHaveLength(0);

  if (!await address.inputValue()) {
    // An offline workstation can still open settings and inspect trusted devices.
    await expect(panel.getByRole('button', {name: 'Включить LAN'})).toBeDisabled();
    await expect(address).toContainText('Нет доступного IPv4-адреса');
    await panel.getByRole('button', {name: 'Закрыть настройки'}).click();
    if (testInfo.project.name === 'desktop') await verifyLauncher(page);
    return;
  }
  await address.selectOption(addresses[0]);
  await panel.getByRole('button', {name: 'Включить LAN'}).click();
  try {
    await expect(panel.getByText('Доступ открыт')).toBeVisible();
    const origin = await panel.locator('.host-url').innerText();
    expect(new URL(origin).protocol).toBe('https:');
    const qr = panel.getByRole('img', {name: 'QR-код адреса сервера'});
    await expect.poll(() => qr.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    await expect(panel.getByRole('button', {name:'Выдать код'})).toBeEnabled();
    const screenshot = testInfo.outputPath('host-settings.png');
    await page.screenshot({path: screenshot, animations:'disabled'});
    await testInfo.attach('Настройки LAN — ' + testInfo.project.name, {path: screenshot, contentType:'image/png'});
    await panel.getByText('Доверие к сертификату', {exact:true}).click();
    await expect(panel.getByRole('heading', {name:'iPhone и iPad'})).toBeVisible();
    await expect(panel.getByRole('heading', {name:'Android'})).toBeVisible();
    const downloaded = page.waitForEvent('download');
    await panel.getByRole('link', {name:'Скачать сертификат (.cer)'}).click();
    const certificate = new X509Certificate(await readFile((await (await downloaded).path())!));
    await expect(panel.locator('.host-fingerprint code')).toHaveText(certificate.fingerprint256);
    await panel.getByText('Доверие к сертификату', {exact:true}).click();

    const client = (route: string, cookie = '', body?: object) => new Promise<{status: number; cookie: string; body: string}>((resolve, reject) => {
      const req = httpsRequest(new URL(route, origin), {
        ca: certificate.toString(), method: body ? 'POST' : 'GET',
        headers: {origin, cookie, 'Content-Type':'application/json'},
      }, res => {
        let result = '';
        res.setEncoding('utf8');
        res.on('data', s => {result += s;});
        res.on('end', () => resolve({status: res.statusCode!, cookie: res.headers['set-cookie']?.[0]?.split(';')[0] || '', body: result}));
      });
      req.on('error', reject);
      req.end(body ? JSON.stringify(body) : undefined);
    });
    expect((await client('/api/state')).status).toBe(401);
    await panel.getByRole('button', {name:'Выдать код'}).click();
    const code = await panel.getByLabel('Одноразовый код').innerText();
    const invitation = panel.getByRole('img', {name:'QR-код одноразового приглашения'});
    await expect(invitation).toHaveAttribute('src', /^data:image\/svg\+xml/);
    await expect.poll(() => invitation.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    const paired = await client('/api/pair', '', {code, name:'Проверочный планшет'});
    expect(paired.status).toBe(200);
    expect((await client('/api/state', paired.cookie)).status).toBe(200);
    expect(JSON.parse((await client('/api/capabilities', paired.cookie)).body)).toEqual({hostSettings:false});
    const device = panel.getByRole('listitem').filter({hasText: 'Проверочный планшет'});
    await expect(device).toBeVisible();
    await device.getByRole('button', {name:'Отозвать доступ'}).click();
    await device.getByRole('button', {name:'Подтвердить отзыв'}).click();
    await expect(device).toHaveCount(0);
    expect((await client('/api/state', paired.cookie)).status).toBe(401);
    await expect.poll(() => panel.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
  } finally {
    const disable = panel.getByRole('button', {name:'Отключить LAN'});
    if (await disable.count()) await disable.click();
    await expect(panel.getByText('Только этот ПК')).toBeVisible();
    await panel.getByRole('button', {name:'Закрыть настройки'}).click();
  }
  await expect(panel).toHaveCount(0);
  if (testInfo.project.name === 'desktop') await verifyLauncher(page);
});
