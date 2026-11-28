import { test, expect } from "@playwright/test";

test("Карьера от выбора базы до общей сохранённой встречи", async ({
  page,
  browser,
}, info) => {
  await page.goto("/");
  const button = (name: string) =>
    page.getByRole("button", { name, exact: true });
  const press = async (name: string) => {
    const drawer = button("Открыть навигацию");
    if ((await drawer.isVisible()) && !(await button(name).isVisible()))
      await drawer.click();
    if (info.project.use.hasTouch) await button(name).tap();
    else await button(name).click();
  };
  const capture = async (name: string) => {
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      animations: "disabled",
      path: info.outputPath(name + ".png"),
      fullPage: true,
    });
  };
  await expect(
    page.getByRole("heading", { name: "Главное меню" }),
  ).toBeVisible();
  await capture("menu");
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
    page.getByRole("heading", { name: "Кабинет менеджера", exact: true }),
  ).toBeVisible();
  await capture("career");
  await press("Состав");
  await capture("roster");
  await press("Действия · ZywOo");
  await press("Открыть профиль");
  await expect(page.locator(".club-profile-copy h2")).toHaveText("ZywOo");
  await capture("profile");
  await press("Характеристики · 58");
  await expect(page.locator(".attribute-row")).toHaveCount(58);
  await capture("skills");
  await press("Глобальный поиск");
  await page
    .getByPlaceholder("Игрок, команда, организация или раздел")
    .fill("ZywOo");
  await page.locator(".search-result").filter({ hasText: "ZywOo" }).click();
  await press("Кабинет");
  await press("Открыть письмо");
  await capture("inbox");
  await press("Организация");
  await capture("organization");
  await press("База сцены");
  await capture("scene");
  await press("Настройки");
  await capture("preferences");
  await press("Сохранения");
  await press("Сохранить карьеру");
  await capture("saves");
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
    await capture("calendar");
    await page
      .getByRole("button", { name: /Протокол/ })
      .first()
      .click();
    await page.getByRole("dialog").getByRole("button", {name:"Статистика", exact:true}).click();
    await expect(page.getByRole("table").locator("tbody tr")).toHaveCount(10);
    await capture("report");
    await press("Закрыть протокол");
    await press("В матч-центр");
    await expect(page.locator(".veto-center, canvas").first()).toBeVisible();
    if (await page.locator(".veto-center").isVisible()) {
      if (await page.getByText("Делегировать оставшиеся ходы", {exact:true}).isVisible()) {
        await page.getByText("Делегировать оставшиеся ходы", {exact:true}).click();
        await press("Капитану");
      }
      await press("Перейти к подготовке");
    }
    await expect(page.locator("canvas").first()).toBeVisible();
    await capture("match");
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
