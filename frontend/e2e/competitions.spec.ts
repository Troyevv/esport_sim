import { expect, test } from "@playwright/test";

test("Ноябрьская карьера · отбор, заявка, сохранение и VRS", async ({
  page,
  hasTouch,
}, info) => {
  test.setTimeout(120000);
  const button = (name: string) =>
    page.getByRole("button", { name, exact: true });
  const press = async (name: string) => {
    const target =
      name === "Входящие"
        ? page.getByRole("button", { name: /^Входящие/ }).first()
        : button(name);
    if (
      [
        "Соревнования",
        "Сохранения",
        "Рейтинг VRS",
        "Входящие",
        "← Главное меню",
      ].includes(name) &&
      !(await target.isVisible()) &&
      (await button("Открыть навигацию").isVisible())
    )
      await button("Открыть навигацию").click();
    if (hasTouch) await target.tap();
    else await target.click();
  };
  const capture = async (name: string) => {
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({ path: info.outputPath(name + ".png") });
  };
  await page.goto("/");
  await press("Новая карьера");
  await page.getByLabel("Редакция базы").selectOption("scene-20261125-clubs/1");
  await page.getByRole("button",{name:"Настроить карьеру",exact:true}).click();
  await page.getByLabel("Имя персонажа").fill("Тренер");
  await page
    .getByLabel("Команда", { exact: true })
    .selectOption({ label: "SINNERS Esports" });
  await press("Создать карьеру");
  await expect(
    page.getByRole("heading", { name: /^(Кабинет команды|День матча)$/ }),
  ).toBeVisible();
  await press("Соревнования");
  await expect(button("Архив")).toBeVisible();
  await capture("calendar");
  const emblems = page.locator(".tc-card svg.competition-mark");
  const paths = await emblems.evaluateAll((nodes) =>
    nodes.map((node) => node.innerHTML),
  );
  expect(paths.length).toBeGreaterThan(20);
  expect(new Set(paths).size).toBe(paths.length);
  await press("Архив");
  await expect(
    page.locator(".tc-result svg.competition-mark").first(),
  ).toBeVisible();
  await press("Календарь турниров");
  await page
    .getByRole("button", {
      name: /CCT Contenders Europe 12 · открытая квалификация 1/,
    })
    .click();
  await page.keyboard.press("Control+k");
  const search = page.getByRole("dialog", {name:"Глобальный поиск"});
  await search.getByRole("textbox", {name:"Поиск по карьере"}).fill("CCT Contenders Europe 12 · открытая квалификация 1");
  await search.getByRole("button").filter({has:page.locator("svg.competition-mark")}).first().click();
  await expect(search).toHaveCount(0);
  await expect(page.locator(".cp-tournament-hero h1")).toContainText("открытая квалификация 1");
  await press("Моя заявка");
  await press("Заявиться на участие");
  await press("Сохранить заявку");
  await expect(page.getByText("Версия 1", { exact: true })).toBeVisible();
  await capture("registration");
  await press("Сохранения");
  await press("Сохранить карьеру");
  await press("Рейтинг VRS");
  await page.getByLabel("Команда", { exact: true }).fill("MOUZ");
  await expect(page.getByText("1960", { exact: true })).toBeVisible();
  await capture("vrs");
  await press("Соревнования");
  await page.getByRole("button", { name: /PGL Major Singapore 2026/ }).click();
  await press("Группы");
  await expect(page.getByText("До начала карьеры").first()).toBeVisible();
  await capture("major");
  await press("Входящие");
  await page
    .locator(".inbox-item")
    .filter({ hasText: "DraculaN Season 8" })
    .first()
    .click();
  await press("Открыть турнир");
  await expect(
    page.getByRole("heading", { name: "DraculaN Season 8", exact: true }),
  ).toBeVisible();
  await press("Сохранения");
  await page
    .locator(".cr-save")
    .filter({ hasText: "Слот 1" })
    .getByRole("button", { name: "Загрузить" })
    .click();
  await press("Соревнования");
  await page
    .getByRole("button", {
      name: /CCT Contenders Europe 12 · открытая квалификация 1/,
    })
    .click();
  await press("Моя заявка");
  await expect(page.getByText("Версия 1", { exact: true })).toBeVisible();

  // All Playwright scenarios share one home server. Return it to the lab for the next client.
  await press("← Главное меню");
  await press("Стенд симуляции");
  await expect(
    page.getByTestId("radar"),
  ).toBeVisible();
});
