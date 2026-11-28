import { test, expect } from "@playwright/test";

test("доска, жесты, библиотека, спарринг и назначение в BO1", async ({
  page,
  browser,
  hasTouch,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const button = (s: string) =>
    page.getByRole("button", { name: s, exact: true });
  const press = async (s: string) => {
    if (hasTouch) await button(s).tap();
    else await button(s).click();
  };
  await page.goto("/?screen=lab");
  await expect(page.getByTestId("connection")).toContainText("На связи");
  if (await page.locator(".mx-broadcast-score").count()) {
    await page.getByText("Новый сценарий", { exact: true }).click();
    await press("Стенд R0");
  }
  await press("Открыть матч BO1");
  await press("Редактор тактик");
  await press("Новая тактика");
  const name = "Петля " + info.project.name;
  await page.getByLabel("Название тактики").fill(name);
  const map = page.getByTestId("tactic-map");
  await expect(map).toHaveAttribute("data-ready", "true");
  const location = async (x: number, y: number) => {
    await map.scrollIntoViewIfNeeded();
    const box = (await map.boundingBox())!;
    const scale = Math.min(box.width / 334, box.height / 234);
    return {
      x: box.x + box.width / 2 + (x - 155) * scale,
      y: box.y + box.height / 2 + (y - 105) * scale,
    };
  };
  const at = async (x: number, y: number) => {
    const p = await location(x, y);
    if (hasTouch) await page.touchscreen.tap(p.x, p.y);
    else await page.mouse.click(p.x, p.y);
  };
  const start = await location(25, 105),
    end = await location(65, 105);
  if (hasTouch) {
    const cdp = await page.context().newCDPSession(page);
    const touch = (
      type: "touchStart" | "touchMove" | "touchEnd",
      arr: { x: number; y: number }[],
    ) =>
      cdp.send("Input.dispatchTouchEvent", {
        type,
        touchPoints: arr.map((p, id) => ({ ...p, id })),
      });
    await touch("touchStart", [start]);
    await touch("touchMove", [end]);
    await touch("touchEnd", []);
    await expect(page.locator(".board-sequence li")).toHaveCount(5);
    const p = await location(155, 105);
    await touch("touchStart", [
      { x: p.x - 20, y: p.y },
      { x: p.x + 20, y: p.y },
    ]);
    await touch("touchMove", [
      { x: p.x - 30, y: p.y + 10 },
      { x: p.x + 50, y: p.y + 10 },
    ]);
    await touch("touchEnd", []);
    await expect(button("Центрировать доску")).not.toHaveText("100%");
    await page.getByRole("button", { name: /Сдвиг/ }).tap();
    await map.scrollIntoViewIfNeeded();
    const origin = await location(155, 105);
    await touch("touchStart", [origin]);
    await touch("touchMove", [{ x: origin.x + 26, y: origin.y + 12 }]);
    await touch("touchEnd", []);
    await press("Центрировать доску");
    await expect(button("Центрировать доску")).toHaveText("100%");
    await cdp.detach();
  } else {
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    await page.mouse.move(end.x, end.y, { steps: 8 });
    await page.mouse.up();
  }
  await expect(page.locator(".board-sequence li")).toHaveCount(5);
  await page.getByRole("button", { name: /Ожидание/ }).click();
  await at(95, 105);
  await expect(page.locator(".board-sequence li")).toHaveCount(6);
  await page.reload();
  await press("Редактор тактик");
  await expect(page.getByLabel("Название тактики")).toHaveValue(name);
  await expect(page.locator(".board-sequence li")).toHaveCount(6);
  await press("Сохранить тактику");
  await expect(page.getByText("Сохранено в библиотеке")).toBeVisible();
  await press("Назначить в BO1");
  await expect(
    page.getByText("Тактика назначена", { exact: false }),
  ).toBeVisible();
  await button("▷ Предпросмотр").click();
  await expect(page.locator(".board-preview")).toContainText("Спарринг");
  await expect
    .poll(() => page.getByLabel("Время спарринга").inputValue())
    .not.toBe("0");
  await press("К редактированию");
  const peer = await browser.newContext({ baseURL: info.project.use.baseURL });
  try {
    const second = await peer.newPage();
    await second.goto("/?screen=lab");
    await second
      .getByRole("button", { name: "Редактор тактик", exact: true })
      .click();
    const library = second.getByRole("button", { name: "▤ Библиотека" });
    if(await library.getAttribute("aria-expanded")!=="true")await library.click();
    await second
      .locator(".board-cards button")
      .filter({ hasText: name })
      .click();
    await expect(second.locator(".board-sequence li")).toHaveCount(6);
    await second.getByLabel("Название тактики").fill(name + " 2");
    await second.getByRole("button", { name: "Сохранить тактику" }).click();
    await expect(second.getByText("Сохранено в библиотеке")).toBeVisible();
    await page.getByLabel("Название тактики").fill(name + " локально");
    await press("Сохранить тактику");
    await expect(
      page.getByRole("status").filter({ hasText: "другом устройстве" }),
    ).toBeVisible();
    page.on("dialog", (dialog) => dialog.accept());
    await press("Предложение штаба");
    await expect(
      page.getByText("План штаба готов к редактированию"),
    ).toBeVisible();
    await page.getByLabel("Название тактики").fill("Двойной выход");
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      )
      .toBeLessThanOrEqual(1);
    await page.screenshot({
      path: info.outputPath("r2-" + info.project.name + ".png"),
      fullPage: true,
    });
    await press("Сохранить тактику");
    await expect(page.getByText("Сохранено в библиотеке")).toBeVisible();
    await press("Создать копию");
    await press("Сохранить тактику");
    await expect(page.getByText("Сохранено в библиотеке")).toBeVisible();
    await press("Удалить");
    await expect(page.getByText("Тактика удалена")).toBeVisible();
    await press("← К матчу");
    await expect(page.locator(".coaching")).toContainText(name + " · в1");
    await press("8×");
    await press("Запустить");
    await expect(page.locator(".plan-line").first()).toContainText(
      name + " · в1",
    );
    await press("Запросить тайм-аут");
    await expect(page.locator(".round-clock")).toContainText("ПАУЗА", {
      timeout: 25000,
    });
    await press("Выбрать тактику");
    await press("Предложение штаба");
    await page.getByLabel("Название тактики").fill("Смена направления");
    await press("Сохранить тактику");
    await expect(page.getByText("Сохранено в библиотеке")).toBeVisible();
    await press("Назначить в BO1");
    await expect(
      page.getByText("Тактика назначена", { exact: false }),
    ).toBeVisible();
    await press("← К матчу");
    await press("Завершить тайм-аут");
    await expect(page.locator(".plan-line").first()).toContainText(
      "Смена направления · в1",
    );
    await press("Пауза просмотра");
    await page.getByText("Новый сценарий", { exact: true }).click();
    await press("Стенд R0");
    expect(errors).toEqual([]);
  } finally {
    await peer.close();
  }
});
