// Exercise the production bundle served by the instance discovered by start.bat.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";

const origin = process.argv[2];
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
  ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
  : { channel: "msedge" });
try {
  const page = await browser.newPage();
  const frames = [];
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("websocket", socket => {
    const url = new URL(socket.url());
    if (url.pathname === "/api/stream" && url.host === new URL(origin).host) {
      socket.on("framereceived", ({ payload }) => frames.push(JSON.parse(payload.toString())));
    }
  });
  const state = await page.request.get(origin + "/api/state");
  assert.equal(state.status(), 200);
  const before = await state.json();
  assert.equal(before.running, false);
  assert.equal(before.world.match.history.length, 2);
  const first = before.world.match.history[0].economy;
  assert.ok(first.T > 0 && first.CT > 0);

  const forbidden = await page.request.get(origin + "/api/state", { headers: { Origin: "https://example.invalid" } });
  assert.equal(forbidden.status(), 403);
  await page.goto(origin + "/?screen=lab");
  await expect(page.getByTestId("connection")).toHaveText("На связи");
  assert.equal(frames[0].context, before.context);
  assert.deepEqual(frames[0].world.match.history, before.world.match.history);
  await page.getByRole("button", { name: "Запустить", exact: true }).click();
  await expect.poll(() => frames.some(f => f.running && f.world.tick > before.world.tick)).toBe(true);
  await page.getByRole("button", { name: "Пауза просмотра", exact: true }).click();
  await expect.poll(() => frames.at(-1).running).toBe(false);
  assert.deepEqual(errors, []);
  console.log("Migrated BO1: HTTP 200, foreign Origin 403, first WebSocket snapshot, UI start and advancing model ticks on port " + new URL(origin).port);
} finally {
  await browser.close();
}
