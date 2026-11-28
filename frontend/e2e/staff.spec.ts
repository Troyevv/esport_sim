import { expect, test } from "@playwright/test";

test("Штаб, назначения и выбор между ECL и Major", async ({
  page,
  hasTouch,
}, info) => {
  test.setTimeout(120000);
  const button = (name: string) =>
    page.getByRole("button", { name, exact: true });
  const press = async (name: string) => {
    const target = button(name);
    if (
      ["Тренерский штаб", "Тактики", "Соревнования", "← Главное меню"].includes(
        name,
      ) &&
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
    await page.screenshot({
      animations: "disabled",
      path: info.outputPath(name + ".png"),
    });
  };
  await page.goto("/");
  await press("Новая карьера");
  await page.getByLabel("Редакция базы").selectOption("scene-20261125-staff/1");
  await page.getByRole("button",{name:"Настроить карьеру",exact:true}).click();
  await page.getByLabel("Имя персонажа").fill("Тренер");
  await page
    .getByLabel("Команда", { exact: true })
    .selectOption({ label: "Team Vitality" });
  await press("Создать карьеру");
  await expect(
    page.getByRole("heading", { name: "Кабинет менеджера" }),
  ).toBeVisible();
  await press("Глобальный поиск");
  const search = page.getByRole("dialog", { name: "Глобальный поиск" });
  await search.getByRole("textbox").fill("TOBIZ");
  await search.getByRole("button", { name: /TOBIZ/ }).click();
  await expect(page.getByText("Оценки компетенций доступны для собственного штаба.")).toBeVisible();
  await expect(page.locator(".staff-office meter")).toHaveCount(0);
  await press("Тренерский штаб");
  await expect(
    page.getByRole("heading", { name: "Главный тренер" }),
  ).toBeVisible();
  await capture("staff");
  await page.locator(".staff-member").filter({ hasText: "MaT" }).click();
  await expect(page.locator(".staff-office meter")).toHaveCount(24);
  await expect(page.getByRole("heading", { name: "Тренерская философия" })).toBeVisible();
  await capture("profile");
  await page
    .locator(".staff-tabs")
    .getByRole("button", { name: "Обязанности" })
    .click();
  await page.getByLabel("Подготовка к Map Veto").selectOption("staff-mat");
  await expect(page.getByLabel("Подготовка к Map Veto")).toHaveValue(
    "staff-mat",
  );
  await page.getByLabel("Подготовка тактик").selectOption("staff-mat");
  await expect(page.getByLabel("Подготовка тактик")).toHaveValue("staff-mat");
  await capture("delegation");
  await page
    .locator(".staff-tabs")
    .getByRole("button", { name: "Занятость" })
    .click();
  await expect(
    page
      .locator(".staff-office p")
      .filter({ hasText: "Подготовка к Map Veto" }),
  ).toHaveCount(1);
  await capture("workload");
  await press("Тактики");
  await press("План · MaT");
  await expect(
    page.getByText("План штаба готов к редактированию"),
  ).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await press("← К радару");
  await press("Соревнования");
  await page
    .getByRole("button", { name: /ESL Challenger League · Europe Cup 13/ })
    .click();
  await press("Моя заявка");
  await press("Заявиться на участие");
  const dialog = page.getByRole("dialog", { name: "Конфликт календаря" });
  await expect(dialog.getByText("PGL Major Singapore 2026")).toBeVisible();
  await capture("conflict");
  await dialog.getByRole("button", { name: /Выбрать ESL/ }).click();
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Отменить участие" }),
  ).toBeVisible();
  await press("← Все соревнования");
  await page.getByRole("button", { name: /PGL Major Singapore 2026/ }).click();
  await press("Моя заявка");
  await expect(page.getByText(/Команда снялась · Регистрация/)).toBeVisible();
  await expect(page.getByText("Версия 1", { exact: true })).toBeVisible();
  await press("← Главное меню");
  await press("Стенд симуляции");
});
