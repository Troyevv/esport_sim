import { expect, test } from "@playwright/test";

test("Менеджер рассчитывает собственный матч и открывает протокол по раундам", async ({page}, info) => {
  const button = (name: string) => page.getByRole("button", {name, exact:true});
  await page.goto("/");
  await button("Новая карьера").click();
  await page.getByLabel("Редакция базы").selectOption("austin-registration/1");
  await page.getByLabel("Имя персонажа").fill("Тренер Vitality");
  await page.getByLabel("Команда",{exact:true}).selectOption({label:"Vitality"});
  await button("Создать карьеру").click();
  await button("Продолжить").click();
  await expect(button("В матч-центр")).toBeVisible();
  await button("Быстро рассчитать матч").click();
  const result = page.getByRole("dialog", {name:"Матч завершён"});
  await expect(result.getByText("Быстрый расчёт по раундам",{exact:false})).toBeVisible();
  await expect(result.getByRole("table")).toHaveCount(2);
  await expect(result.getByRole("columnheader",{name:"KAST"})).toHaveCount(2);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({animations:"disabled",path:info.outputPath("quick-match.png")});
  await result.getByRole("button",{name:"Закрыть протокол"}).click();
  await expect(button("Продолжить")).toBeVisible();
  await page.reload();
  await button("Продолжить карьеру").click();
  await expect(button("Продолжить")).toBeVisible();
  if (await button("Открыть навигацию").isVisible()) await button("Открыть навигацию").click();
  await button("← Главное меню").click();
  await button("Стенд симуляции").click();
});
