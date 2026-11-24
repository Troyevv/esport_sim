import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

export async function touchCamera(page: Page) {
  const radar = page.getByTestId("radar");
  const canvas = radar.locator("canvas");
  await canvas.scrollIntoViewIfNeeded();
  const rect = await canvas.boundingBox();
  if (!rect) throw new Error("Радар не отображается");
  const x = rect.x + rect.width / 2;
  const y = rect.y + rect.height / 2;
  const cdp = await page.context().newCDPSession(page);
  const dispatch = (
    type: "touchStart" | "touchMove" | "touchEnd",
    points: Array<[number, number]>,
  ) =>
    cdp.send("Input.dispatchTouchEvent", {
      type,
      touchPoints: points.map(([x, y], id) => ({ x, y, id })),
    });

  const initialZoom = Number(await radar.getAttribute("data-zoom"));
  await dispatch("touchStart", [
    [x - 24, y],
    [x + 24, y],
  ]);
  await dispatch("touchMove", [
    [x - 49, y],
    [x + 49, y],
  ]);
  await dispatch("touchEnd", []);
  await expect
    .poll(async () => Number(await radar.getAttribute("data-zoom")))
    .toBeGreaterThan(initialZoom);

  const initialPan = await radar.getAttribute("data-pan-x");
  await dispatch("touchStart", [[x, y]]);
  await dispatch("touchMove", [[x + 48, y + 20]]);
  await dispatch("touchEnd", []);
  await expect(radar).not.toHaveAttribute("data-pan-x", initialPan!);
  await cdp.detach();
}
