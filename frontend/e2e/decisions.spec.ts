import { expect, test } from "@playwright/test";

test("Aurora · приоритет турнира, центр решений и регистрация", async ({
  page,
  hasTouch,
}, info) => {
  const button = (name: string) =>
    page.getByRole("button", { name, exact: true });
  const press = async (name: string) => {
    const target = button(name);
    if (
      ["Соревнования", "← Главное меню"].includes(name) &&
      !(await target.isVisible()) &&
      (await button("Открыть навигацию").isVisible())
    ) {
      await button("Открыть навигацию").click();
    }
    if (hasTouch) await target.tap();
    else await target.click();
  };
  await page.goto("/");
  await press("Новая карьера");
  await page.getByLabel("Редакция базы").selectOption("scene-20261125-staff/1");
  await page.getByLabel("Имя персонажа").fill("Тренер Aurora");
  await page
    .getByLabel("Команда", { exact: true })
    .selectOption({ label: "Aurora Gaming" });
  await press("Создать карьеру");
  await expect(
    page.getByRole("heading", { name: "Кабинет менеджера" }),
  ).toBeVisible();
  await press("Соревнования");
  await page
    .getByRole("button", { name: /ESL Challenger League · Europe Cup 13/ })
    .click();
  await press("Моя заявка");
  await press("Заявиться на участие");
  const conflict = page.getByRole("dialog", { name: "Конфликт календаря" });
  await expect(conflict.getByText("PGL Major Singapore 2026")).toBeVisible();
  await conflict.getByRole("button", { name: /Выбрать ESL/ }).click();
  await expect(button("Решения · 1")).toBeVisible();
  await press("Решения · 1");
  const center = page.getByRole("dialog", { name: "Центр решений" });
  await expect(center.getByText("Зарегистрируйте пятёрку")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    animations: "disabled",
    path: info.outputPath("manager-decisions.png"),
  });
  await center.getByRole("button", { name: "Открыть заявку" }).click();
  await press("Сохранить заявку");
  await expect(button("Продолжить")).toBeVisible();
  await expect(page.getByText("Версия 1", { exact: true })).toBeVisible();
  await page.reload();
  await press("Продолжить карьеру");
  await expect(button("Продолжить")).toBeVisible();
  await press("← Главное меню");
  await press("Стенд симуляции");
  await expect(page.locator("button.database-entry")).toBeVisible();
});
