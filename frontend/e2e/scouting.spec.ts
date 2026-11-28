import { expect, test, type Locator } from "@playwright/test";

test("Скаутский отдел ведёт досье и сохраняет результаты просмотра", async ({
  page,
  hasTouch,
}, info) => {
  test.setTimeout(150000);
  const button = (name: string) =>
    page.getByRole("button", { name, exact: true });
  async function press(name: string) {
    if (
      ["Скаутский отдел", "← Главное меню"].includes(name) &&
      !(await button(name).first().isVisible()) &&
      (await button("Открыть навигацию").isVisible())
    )
      await button("Открыть навигацию").click();
    const b = button(name).first();
    if (hasTouch) await b.tap();
    else await b.click();
  }
  async function tab(name: string) {
    await expect(
      page.getByRole("heading", { name: "Скаутский центр", exact: true }),
    ).toBeVisible();
    const select = page.getByLabel("Раздел скаутинга", { exact: true });
    if (await select.isVisible()) await select.selectOption({ label: name });
    else
      await page
        .getByRole("navigation", { name: "Разделы скаутинга" })
        .getByRole("button", { name, exact: true })
        .click();
  }
  async function shot(key: string, target?: Locator) {
    if (target) await target.scrollIntoViewIfNeeded();
    else if (!(await page.getByRole("dialog").count()))
      await page.locator(".scout-center h2").first().scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(key + ".png"),
      animations: "disabled",
    });
  }
  await page.goto("/");
  await press("Новая карьера");
  await page.getByLabel("Редакция базы").selectOption("austin-registration/1");
  await page.getByRole("button",{name:"Настроить карьеру",exact:true}).click();
  await page.getByLabel("Имя персонажа").fill("Скаут");
  await page
    .getByLabel("Команда", { exact: true })
    .selectOption({ label: "Vitality" });
  await press("Создать карьеру");
  await expect(
    page.getByRole("heading", { name: "Кабинет менеджера" }),
  ).toBeVisible();
  await press("Скаутский отдел");
  await tab("Поиск игроков");
  await page.getByLabel("Имя игрока").fill("kyxsan");
  await expect(page.locator(".scout-row")).toHaveCount(1);
  await shot("search");
  const criteria = page.getByText("Критерии поиска", { exact: true });
  await criteria.click();
  await shot("criteria");
  await criteria.click();
  await press("Сравнить");
  await press("Изучить");
  await press("Назначить задание");
  await expect(button("Отменить задание")).toBeVisible();
  await shot("tasks");
  await tab("Шорт-листы");
  await page.getByLabel("Новая категория").fill("Капитаны");
  await press("Создать категорию");
  await press("Добавить игрока");
  await expect(button("Удалить из списка")).toBeVisible();
  await shot("shortlists");
  await tab("Сравнение");
  await page
    .getByLabel("Игрок", { exact: true })
    .selectOption({ label: "ropz" });
  await press("Добавить к сравнению");
  await expect(page.getByRole("table").getByText("Текущий OVR")).toBeVisible();
  await shot("compare");
  await tab("Просмотры");
  await page
    .getByLabel("Игрок", { exact: true })
    .selectOption({ label: "Vexite" });
  await page.getByRole("combobox", { name: "Длительность" }).selectOption("3");
  await press("Пригласить игрока");
  await expect(page.getByText(/Согласие игрока/)).toBeVisible();
  await shot("trials");
  await tab("Персонал");
  await page
    .getByLabel("Распределение заданий скаутам")
    .selectOption({ index: 1 });
  await expect(
    page.getByLabel("Распределение заданий скаутам"),
  ).not.toHaveValue("");
  await shot("staff");
  await press("Продолжить");
  await expect(button("В матч-центр").first()).toBeVisible();
  await tab("Просмотры");
  await expect(button("Итоговый отчёт").first()).toBeVisible();
  await press("Итоговый отчёт");
  const trialReport = page.getByRole("dialog");
  await expect(
    trialReport.getByRole("heading", { name: /Vexite/ }),
  ).toBeVisible();
  await expect(
    trialReport.getByRole("heading", { name: "Основания оценки" }),
  ).toBeVisible();
  await shot("trial-finished");
  await trialReport.getByRole("button", { name: "Закрыть" }).click();
  await tab("Региональное покрытие");
  await shot("regions");
  await tab("Отчёты");
  const entry = page
    .locator(".scout-entry")
    .filter({ hasText: "kyxsan" })
    .first();
  await expect(entry).toBeVisible();
  await shot("reports");
  await entry.click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "Основания оценки" }),
  ).toBeVisible();
  await shot("report");
  await dialog.getByRole("button", { name: "Закрыть", exact: true }).click();
  await tab("Обзор");
  await shot("overview");
  await tab("Поиск игроков");
  await page.locator(".scout-row .entity-button").first().click();
  await expect(
    page.getByRole("heading", { name: "Знания организации" }),
  ).toBeVisible();
  await expect(page.getByText(/последнее наблюдение/)).toBeVisible();
  await shot(
    "profile",
    page.getByRole("heading", { name: "Знания организации" }),
  );
  await press("← Главное меню");
  await press("Стенд симуляции");
});
