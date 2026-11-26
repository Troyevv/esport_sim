import { expect, test } from "@playwright/test";

test("Ноябрьская карьера · отбор, заявка, сохранение и VRS", async ({page,hasTouch}, info)=>{
  test.setTimeout(120000);
  const button=(name:string)=>page.getByRole("button",{name,exact:true});
  const press=async(name:string)=>{
    const target=button(name);
    if(["Соревнования","Сохранения","Рейтинг VRS"].includes(name) && !await target.isVisible() && await button("Открыть навигацию").isVisible()) await button("Открыть навигацию").click();
    if(hasTouch)await target.tap(); else await target.click();
  };
  const capture=async(name:string)=>{
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(name+".png")});
  };
  await page.goto("/");
  await press("Новая карьера");
  await page.getByLabel("Редакция базы").selectOption("scene-20261125-clubs/1");
  await page.getByLabel("Имя персонажа").fill("Тренер");
  await page.getByLabel("Команда",{exact:true}).selectOption({label:"SINNERS Esports"});
  await press("Создать карьеру");
  await expect(page.getByRole("heading",{name:"Кабинет менеджера"})).toBeVisible();
  await press("Соревнования");await expect(button("Архив")).toBeVisible();
  await capture("calendar");
  await page.getByRole("button",{name:/CCT Contenders Europe 12 · открытая квалификация 1/}).click();
  await press("Моя заявка");await press("Заявиться на участие");await press("Сохранить заявку");
  await expect(page.getByText("Версия 1",{exact:true})).toBeVisible();
  await capture("registration");
  await press("Сохранения");await press("Сохранить карьеру");
  await press("Рейтинг VRS");await page.getByLabel("Команда",{exact:true}).fill("MOUZ");
  await expect(page.getByText("1960",{exact:true})).toBeVisible();await capture("vrs");
  await press("Соревнования");await page.getByRole("button",{name:/PGL Major Singapore 2026/}).click();
  await press("Сетки");await expect(page.getByText("До начала карьеры").first()).toBeVisible();
  await capture("major");
});
