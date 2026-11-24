import { test, expect } from "@playwright/test";
test("Пакет, поиск, правка, перенос и BO1", async ({ page }, info) => {
  await page.goto("/");
  const open = page.getByRole("button", { name: "База сцены", exact: true });
  if (info.project.use.hasTouch) await open.tap();
  else await open.click();
  await page.getByLabel("Поиск", { exact: true }).fill("ZywOo");
  await page.getByRole("button", { name: /ZywOo/ }).first().click();
  await expect(
    page.getByText("Mathieu Herbaut", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByLabel(/Общий рейтинг/)).toBeVisible();
  await page.screenshot({
    path: info.outputPath("player-profile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Навыки · 58" }).click();
  await expect(page.locator(".pf-attribute")).toHaveCount(58);
  await expect(page.getByText("AIM", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("database-skills.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Редактировать", exact: true })
    .click();
  await page
    .getByLabel("Группа характеристик")
    .selectOption("Психология и развитие");
  await page
    .getByRole("spinbutton", { name: "Лояльность", exact: true })
    .fill("61");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: /сохранена/ }),
  ).toBeVisible();
  await expect(
    page.locator(".pf-attribute").filter({ hasText: "Лояльность" }),
  ).toContainText("61");
  await page.getByRole("button", { name: "Профиль", exact: true }).click();
  await page
    .locator(".pf-section")
    .filter({ has: page.getByRole("heading", { name: /Команды в срезе/ }) })
    .getByRole("button", { name: /Vitality/ })
    .click();
  await expect(page.locator(".pf-heading h2")).toHaveText("Vitality");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Экспорт", exact: true }).click();
  const file = await download;
  await page.getByLabel("Файл пакета").setInputFiles((await file.path())!);
  await expect(page.getByText("Пакет проверен и открыт")).toBeVisible();
  await page.getByRole("button", { name: "Подбор BO1" }).click();
  await page.getByLabel("Ваша пятёрка").selectOption({ label: "Vitality" });
  await page
    .getByRole("combobox", { name: /Соперник/ })
    .selectOption({ label: "Falcons" });
  await page.getByRole("button", { name: "Начать BO1" }).click();
  await expect(page.getByRole("region", { name: "Счёт матча" })).toContainText(
    "Falcons",
  );
  await expect(page.getByText(/Составы из базы/)).toBeVisible();
  await page.getByText("Новый сценарий", { exact: true }).click();
  await page.getByRole("button", { name: "Стенд R0", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Тактический радар" }),
  ).toBeVisible();
});
