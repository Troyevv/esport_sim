import { openLab } from "./openLab";
import { test, expect } from "@playwright/test";
test("Пакет, поиск, правка, перенос и BO1", async ({ page }, info) => {
  await openLab(page);
  const open = page.getByRole("button", { name: "База сцены", exact: true });
  if (info.project.use.hasTouch) await open.tap();
  else await open.click();
  await expect(page.getByLabel("Пакет и редакция")).toHaveValue(
    "scene-20261125-staff/1",
  );
  const catalog = page.getByLabel("Пакет и редакция");
  const target = (await catalog
    .locator('option[value^="austin-registration/"]')
    .first()
    .getAttribute("value"))!;
  // Enter the search while the requested revision is still in flight.
  let release!: () => void;
  const pending = new Promise<void>((done) => {
    release = done;
  });
  await page.route(
    "**/api/database/" + target,
    async (route) => {
      await pending;
      await route.continue();
    },
    { times: 1 },
  );
  await catalog.selectOption(target);
  const search = page.getByLabel("Поиск", { exact: true });
  await search.fill("ZywOo");
  const sections = page.getByRole("navigation", { name: "Раздел базы" });
  await expect(sections.getByRole("button", { name: /Организации/ })).toBeDisabled();
  release();
  await expect(catalog).toHaveValue(target);
  await expect(search).toHaveValue("ZywOo");
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
  await page.getByRole("button", { name: "Подбор матча" }).click();
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
    page.getByTestId("radar"),
  ).toBeVisible();
});

test("Профили организации, штаба и новая редакция", async ({ page }, info) => {
  await openLab(page);
  await page.getByRole("button", { name: "База сцены", exact: true }).click();
  const catalog = page.getByLabel("Пакет и редакция");
  await catalog.selectOption(
    (await catalog
      .locator('option[value^="austin-registration/"]')
      .first()
      .getAttribute("value")) as string,
  );
  const tabs = page.getByRole("navigation", { name: "Раздел базы" });
  await tabs.getByRole("button", { name: /Организации/ }).click();
  await page
    .locator(".db-list")
    .getByRole("button", { name: /Team Vitality/ })
    .click();
  await expect(page.locator(".pf-facts")).toContainText("2013");
  await page
    .locator(".pf-roster")
    .getByRole("button", { name: /XTQZZZ/ })
    .click();
  await expect(page.locator(".pf-heading")).toContainText("Rémy Quoniam");
  await page.screenshot({
    path: info.outputPath("staff-profile.png"),
    fullPage: true,
  });
  await tabs.getByRole("button", { name: /Организации/ }).click();
  await page.getByRole("button", { name: "Создать", exact: true }).click();
  await page.getByLabel("Название", { exact: true }).fill("Клуб редактора");
  await page.getByLabel("Год основания", { exact: true }).fill("2024");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(page.locator(".pf-heading h2")).toHaveText("Клуб редактора");
  await page
    .getByRole("button", { name: "Редактировать", exact: true })
    .click();
  await page.getByRole("button", { name: "Копировать", exact: true }).click();
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(page.locator(".pf-heading h2")).toHaveText(
    "Клуб редактора · копия",
  );
  for (const name of ["Клуб редактора · копия", "Клуб редактора"]) {
    await page.getByLabel("Поиск", { exact: true }).fill(name);
    await page
      .locator(".db-list")
      .getByRole("button", { name: new RegExp(name) })
      .first()
      .click();
    await page
      .getByRole("button", { name: "Редактировать", exact: true })
      .click();
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Удалить", exact: true }).click();
    await expect(
      page.getByRole("status").filter({ hasText: /Запись удалена/ }),
    ).toBeVisible();
  }
});
