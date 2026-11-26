import { expect, test } from "@playwright/test";

if (process.env.ESPORT_CS2_QA) {
  test("установленные карты в матч-центре и на доске", async ({page}, info) => {
    test.setTimeout(360000);
    page.setDefaultTimeout(15000);
    const errors:string[]=[];
    page.on("pageerror", e => errors.push(e.message));
    const catalog=await (await page.request.get("/api/maps")).json() as {id:string;name:string}[];
    expect(catalog).toHaveLength(10);
    const button=(name:string)=>page.getByRole("button",{name,exact:true});
    await page.goto("/?screen=lab");
    await expect(page.getByTestId("connection")).toContainText("На связи");
    for (const map of catalog.filter(m=>m.id!=="depo")) {
      await test.step(map.name,async () => {
      const previous=await (await page.request.get("/api/state")).json();
      if (previous.world.match) {
        await page.getByText("Новый сценарий",{exact:true}).click();
        await button("Стенд R0").click();
      }
      await page.getByRole("combobox",{name:"Карта",exact:true}).selectOption(map.id);
      const radarRequest = page.waitForResponse(r=>r.url().includes("/"+map.id+"/radar.png?layer=default") && r.ok());
      await button("Открыть матч BO1").click();
      await radarRequest;
      await expect(page.getByText(map.name+" · BO1",{exact:true})).toBeVisible();
      await expect(page.getByTestId("radar")).toHaveAttribute("data-ready","true");
      await button("Запустить").click();
      await expect.poll(async()=> (await (await page.request.get("/api/state")).json()).world.match.phase,{timeout:30000}).toBe("live");
      await button("Пауза просмотра").click();
      const state=await (await page.request.get("/api/state")).json();
      expect(state.world.map.id).toBe(map.id);
      expect(state.world.agents.every((a:{z?:number})=>Number.isFinite(a.z))).toBeTruthy();
      if (state.world.map.layers?.lower) {
        await button("Сменить этаж").click();
        await expect(button("Сменить этаж")).toHaveText("Нижний");
      }
      await page.screenshot({path:info.outputPath(map.id+".png")});
      await button("Редактор тактик").click();
      await expect(page.getByTestId("tactic-map")).toHaveAttribute("data-ready","true");
      if (map.id === "de_nuke") {
        const buy = page.getByRole("combobox", {name:"Закупка"});
        await buy.selectOption("Бонусная");
        page.once("dialog", dialog => dialog.accept());
        await button("Предложение штаба").click();
        await expect(page.getByText("План штаба готов к редактированию")).toBeVisible();
        await button("▷ Предпросмотр").click();
        await expect(page.getByText(/Seed 42 · Бонусная.*закуплено на/)).toBeVisible();
        await button("К редактированию").click();
        const coordinates = page.locator(".board-sequence li small").first();
        await expect(coordinates).toBeVisible();
        await expect(coordinates).not.toHaveText(/\.\d{2,}/);
      }
      await page.screenshot({path:info.outputPath(map.id+"-board.png")});
      await page.reload();
      await expect(page.getByTestId("connection")).toContainText("На связи");
      });
    }
    expect(errors).toEqual([]);
  });
}
