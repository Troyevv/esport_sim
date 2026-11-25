import { test, expect } from "@playwright/test";

test("Карьера от выбора базы до общей сохранённой встречи", async ({
  page,
  browser,
}, info) => {
  await page.goto("/");
  const button = (name: string) =>
    page.getByRole("button", { name, exact: true });
  const press = async (name: string) =>
    info.project.use.hasTouch ? button(name).tap() : button(name).click();
  const capture = async (name: string) => {
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(name + ".png"),
      fullPage: true,
    });
  };
  await expect(
    page.getByRole("heading", { name: "Главное меню" }),
  ).toBeVisible();
  await press("Новая карьера");
  await page.getByLabel("Редакция базы").selectOption("austin-registration/1");
  await page.getByLabel("Имя персонажа").fill("Алексей");
  await page
    .getByLabel("Команда", { exact: true })
    .selectOption({ label: "Vitality" });
  await page.getByLabel("Должность").selectOption("owner");
  await capture("creation");
  await press("Создать карьеру");
  await expect(
    page.getByRole("heading", { name: "Vitality", exact: true }),
  ).toBeVisible();
  await capture("career");
  await press("Состав");
  await page.getByRole("button", { name: /ZywOo/ }).click();
  await expect(page.locator(".pf-heading h2")).toHaveText("ZywOo");
  await capture("squad");
  await press("Сохранения");
  await press("Сохранить карьеру");
  await expect(
    page.locator(".cr-save").filter({ hasText: "Слот 1" }),
  ).toBeVisible();
  const peer = await browser.newPage({ baseURL: "http://127.0.0.1:8766" });
  try {
    await peer.goto("/");
    await peer.getByRole("button", { name: "Продолжить карьеру" }).click();
    await press("Продолжить");
    await expect(
      peer.getByRole("button", { name: "В матч-центр" }),
    ).toBeVisible();
    await press("Календарь");
    await page.getByLabel("Показать").selectOption("all");
    await page
      .getByRole("button", { name: /Протокол/ })
      .first()
      .click();
    await expect(page.getByRole("table").locator("tbody tr")).toHaveCount(10);
    await capture("calendar");
    await press("В матч-центр");
    await expect(page.locator("canvas").first()).toBeVisible();
    await press("← Карьера");
    await press("Сохранения");
    await page
      .locator(".cr-save")
      .filter({ hasText: "Слот 1" })
      .getByRole("button", { name: "Загрузить" })
      .click();
    await expect(peer.locator(".cr-time time")).toHaveText("9 мая 2025 г.");
    await press("← Главное меню");
    await press("Стенд симуляции");
    await expect(
      page.getByRole("heading", { name: "Тактический радар" }),
    ).toBeVisible();
  } finally {
    await peer.close();
  }
});
