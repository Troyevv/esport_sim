import { expect, type Page } from "@playwright/test";

// The same server can still have a career selected after a preceding test.
export async function openLab(page: Page) {
  if ((await (await page.request.get("/api/state")).json()).careerId) {
    await page.goto("/");
    await page.getByRole("button", {name: "Стенд симуляции", exact: true}).click();
    await expect.poll(async () => (await (await page.request.get("/api/state")).json()).careerId).toBeFalsy();
  } else {
    await page.goto("/?screen=lab");
  }
}

export async function openMatchBoard(page: Page) {
  const menu = page.locator(".mx-match-options");
  if (await menu.getAttribute("open") === null) await menu.locator("summary").click();
  await page.getByRole("button", {name:"Редактор тактик", exact:true}).click();
}
