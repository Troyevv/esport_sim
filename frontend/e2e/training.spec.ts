import { expect, test } from "@playwright/test";

test("Тренировочная неделя, профиль развития, пракк и отчёт", async ({
  page,
  hasTouch,
}, info) => {
  test.setTimeout(120000);
  const button = (name: string) =>
    page.getByRole("button", { name, exact: true });
  async function press(name: string) {
    const mobileNav = page.getByLabel("Раздел центра");
    if (
      (await mobileNav.isVisible()) &&
      [
        "Индивидуальная подготовка",
        "Пракки",
        "Делегирование",
        "Нагрузка",
        "Карты и тактики",
        "Отчёты",
      ].includes(name)
    ) {
      await mobileNav.selectOption({ label: name });
      return;
    }
    const target = button(name);
    if (
      !(await target.isVisible()) &&
      (await button("Открыть навигацию").isVisible())
    )
      await button("Открыть навигацию").click();
    if (hasTouch) await target.tap();
    else await target.click();
  }
  async function capture(name: string) {
    if (!(await page.getByRole("dialog").count()))
      await page
        .locator(".training-center h2:visible")
        .first()
        .scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(name + ".png"),
      animations: "disabled",
    });
  }
  await page.goto("/");
  await press("Новая карьера");
  await page.getByLabel("Редакция базы").selectOption("austin-registration/1");
  await page.getByRole("button",{name:"Настроить карьеру",exact:true}).click();
  await page.getByLabel("Имя персонажа").fill("Подготовка");
  await page
    .getByLabel("Команда", { exact: true })
    .selectOption({ label: "Vitality" });
  await press("Создать карьеру");
  await expect(
    page.getByRole("heading", { name: "Кабинет менеджера" }),
  ).toBeVisible();
  await press("Тренировочный центр");
  await capture("week");
  await press("Добавить занятие 2025-05-09");
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Направление").selectOption("recovery");
  await capture("session");
  await press("Сохранить занятие");
  await expect(dialog).not.toBeVisible();
  await page.getByLabel("Название шаблона").fill("Соревновательная");
  await press("Сохранить неделю");
  await expect(
    page.getByLabel("Сохранённая неделя").locator("option"),
  ).toHaveCount(2);
  await press("Индивидуальная подготовка");
  await page.getByLabel("Осваиваемая роль").selectOption("igl");
  await page.getByLabel("Интенсивность").selectOption("0.65");
  await page.getByLabel("Приоритет 1", { exact: true }).selectOption("aim");
  await press("Сохранить программу");
  await expect(
    page.getByText("Изменения сохранены", { exact: true }),
  ).toBeVisible();
  await capture("program");
  await press("Делегирование");
  await page.getByLabel("Тренировочное расписание").selectOption({ index: 1 });
  await expect(page.getByLabel("Тренировочное расписание")).not.toHaveValue("");
  await capture("delegation");
  await press("Пракки");
  await page.getByLabel("Дата пракка").fill("2025-05-10");
  // Use a free opponent on this date from the real career calendar.
  const career = (await (await page.request.get("/api/career")).json()).active;
  const busy = new Set(
    career.queue
      .filter((e: { date: string }) => e.date === "2025-05-10")
      .flatMap((e: { teams: string[] }) => e.teams),
  );
  const options = Object.keys(career.teams).filter((t) => t !== career.team);
  await page
    .getByRole("combobox", { name: "Соперник", exact: true })
    .selectOption(options.find((t) => !busy.has(t))!);
  await press("Назначить пракк");
  await expect(button("Отменить пракк")).toBeVisible();
  await capture("practice");
  await press("Продолжить");
  await expect(button("В матч-центр").first()).toBeVisible();
  await press("Нагрузка");
  await expect(page.getByText("Усталость по дням").first()).toBeVisible();
  await capture("workload");
  await press("Карты и тактики");
  await capture("mastery");
  await press("Отчёты");
  await expect(page.locator(".training-log").first()).toBeVisible();
  await capture("reports");
  await press("Протокол пракка");
  await expect(dialog.getByText("Протокол матча")).toBeVisible();
  await dialog.getByRole("button",{name:"Статистика",exact:true}).click();
  await expect(dialog.locator("table").first()).toBeVisible();
  await capture("pcw-report");
  await dialog.getByRole("button", { name: "Закрыть", exact: true }).click();
  await press("Календарь");
  await page.locator(".calendar-grid, .calendar-agenda").first().waitFor();
  const daySchedule = page.getByRole("button", {name: /^Тренировки · [0-9]+$/}).first();
  if (await page.locator(".calendar-agenda").isVisible()) await daySchedule.click();
  else await press("Открыть расписание");
  await expect(
    page.getByRole("heading", { name: "Тренировки" }),
  ).toBeVisible();
  await press("← Главное меню");
  await press("Стенд симуляции");
});
