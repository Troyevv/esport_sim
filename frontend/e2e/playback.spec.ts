import { expect, test } from "@playwright/test";
import { RadarPlayback } from "../src/playback";
import type { Frame } from "../src/session";

// A screencast adds per-frame encoding work to the measurement.
test.use({
  trace: "off",
  deviceScaleFactor: async ({ hasTouch }, use) => {
    await use(hasTouch ? 2 : 1);
  },
});

const point = (x: number, y = 15, heading = 0) => ({
  id: "T1",
  name: "Sable",
  team: "T" as const,
  x,
  y,
  heading,
  status: "",
  visible: [],
  knowledge: [],
});
function frame(
  tick: number,
  agent = point(15),
  options: Partial<Frame> = {},
): Frame {
  return {
    context: "home",
    running: true,
    speed: 1,
    revision: 0,
    sequence: tick,
    hasSave: false,
    ...options,
    world: {
      map: {
        id: "test",
        version: 1,
        name: "",
        author: "",
        width: 100,
        height: 100,
        walls: [{ x: 20, y: 20, w: 10, h: 10 }],
        zones: [],
        spawns: [],
      },
      seed: 42,
      view: "full",
      agents: [agent],
      tick,
      time: tick / 10,
      events: [],
    },
  };
}

test("интерполяция поз, безопасные повороты и границы подтверждённых данных", () => {
  const p = new RadarPlayback();
  p.push(frame(0, point(15, 15, 3.1)), true, 0);
  const one = frame(1, point(17, 15, -3.1));
  p.push(one, true, 100);
  expect(p.sample("T1", 175).x).toBeCloseTo(16);
  expect(Math.abs(p.sample("T1", 175).heading)).toBeCloseTo(Math.PI);
  p.push(one, true, 180); // repeated heartbeat
  expect(p.sample("T1", 200).x).toBeCloseTo(16.5);
  expect(p.sample("T1", 690).x).toBe(17);
  p.push(frame(3, point(25)), true, 710); // missing snapshots and stall
  expect(p.sample("T1", 710).x).toBe(25);
  const across = frame(4, point(25, 35));
  p.push(across, true, 810);
  expect(p.sample("T1", 880).y).toBe(15);
  expect(p.sample("T1", 1000).y).toBe(35);

  const fast = frame(4, point(15, 15), { speed: 4 });
  p.push(fast, true, 1000);
  const turn = frame(8, point(35, 35), { speed: 4 });
  turn.world.motion = {
    startTick: 4,
    tracks: {
      T1: [
        [15, 15, 0],
        [25, 15, 0],
        [35, 15, 0],
        [35, 25, 1.57],
      ],
    },
  };
  p.push(turn, true, 1100);
  expect(p.sample("T1", 1175)).toMatchObject({ x: 35, y: 15 });
  expect(p.sample("T1", 1212.5)).toMatchObject({ x: 35, y: 30 });
  p.push({ ...turn, running: false }, true, 1215);
  expect(p.sample("T1", 1215)).toMatchObject({ x: 35, y: 35 });
  for (const context of ["reset", "loaded"]) {
    p.push(frame(0, point(15), { context }), true, 1300);
    expect(p.sample("T1", 1300).x).toBe(15);
  }
  const fresh = frame(1, point(17), { context: "loaded" });
  p.push(fresh, true, 1400);
  p.push(fresh, false, 1410);
  expect(p.sample("T1", 1410).x).toBe(17);
  p.push(frame(2, point(19), { context: "loaded" }), true, 1500);
  expect(p.sample("T1", 1500).x).toBe(19);
});

test("радар показывает промежуточные положения между сетевыми снимками", async ({
  page,
  hasTouch,
}, info) => {
  await page.addInitScript(() => {
    const probe = {
      frames: [] as { at: number; cost: number; x: number; y: number }[],
      screen: null as { x: number; y: number } | null,
    };
    Object.assign(window, {
      radarProbe: probe,
      __PIXI_APP_INIT__: (app: any) => {
        const render = app.render.bind(app);
        app.render = () => {
          const before = performance.now();
          render();
          const m = app.stage.getChildByLabel("CT1", true);
          if (!m) return;
          probe.frames.push({
            at: before,
            cost: performance.now() - before,
            x: m.x,
            y: m.y,
          });
          const rect = app.canvas.getBoundingClientRect(),
            pos = m.getGlobalPosition();
          probe.screen = { x: rect.x + pos.x, y: rect.y + pos.y };
        };
      },
    });
  });
  await page.goto("/");
  const radar = page.getByTestId("radar");
  await expect(radar).toHaveAttribute("data-ready", "true");
  const control = (name: string) =>
    page.getByRole("button", { name, exact: true });
  if (await control("Пауза").count()) await control("Пауза").click();
  await control("1×").click();
  await control("Запустить").click();
  await radar.scrollIntoViewIfNeeded();
  await page.waitForFunction(
    () => (window as any).radarProbe.frames.length > 12,
  );
  const report = await page.evaluate(async () => {
    const probe = (window as any).radarProbe;
    probe.frames.length = 0;
    await new Promise((r) => setTimeout(r, 3000));
    const f = probe.frames as {
      at: number;
      cost: number;
      x: number;
      y: number;
    }[];
    const intervals = f
      .slice(1)
      .map((row, i) => row.at - f[i].at)
      .sort((a, b) => a - b);
    const costs = f.map((row) => row.cost).sort((a, b) => a - b);
    const quantile = (v: number[], q: number) =>
      Number(v[Math.floor((v.length - 1) * q)].toFixed(2));
    return {
      pixelRatio: devicePixelRatio,
      frames: f.length,
      fps: ((f.length - 1) * 1000) / (f.at(-1)!.at - f[0].at),
      intervalMedianMs: quantile(intervals, 0.5),
      intervalP95Ms: quantile(intervals, 0.95),
      renderP95Ms: quantile(costs, 0.95),
      intermediate: f.filter(
        (p) => !Number.isInteger(p.x) || !Number.isInteger(p.y),
      ).length,
    };
  });
  console.log("RADAR", info.project.name, JSON.stringify(report));
  await info.attach("Время кадров радара", {
    body: JSON.stringify(report, null, 2),
    contentType: "application/json",
  });
  expect(report.intermediate).toBeGreaterThan(8);
  expect(report.fps).toBeGreaterThan(38);
  expect(report.renderP95Ms).toBeLessThan(16.7);
  // Select using the Pixi marker's actual screen coordinates, while the clock runs.
  const pos = await page.evaluate(() => (window as any).radarProbe.screen);
  if (hasTouch) await page.touchscreen.tap(pos.x, pos.y);
  else await page.mouse.click(pos.x, pos.y);
  await expect(page.getByRole("button", { name: /Atlas/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await control("Пауза").click();
});

test("нажатие выбирает отображаемого игрока при расхождении с последним снимком", async ({
  page,
  hasTouch,
}) => {
  let stream: import("@playwright/test").WebSocketRoute | undefined;
  const first = frame(0, point(51), { speed: 8 });
  first.world.agents.push({
    ...point(35),
    id: "CT1",
    team: "CT",
    name: "Atlas",
  });
  await page.addInitScript(() => {
    Object.assign(window, {
      __PIXI_APP_INIT__: (app: unknown) =>
        Object.assign(window, { testPixi: app }),
    });
  });
  await page.routeWebSocket("**/api/stream**", (route) => {
    stream = route;
    route.send(JSON.stringify(first));
  });
  // Hold presentation time while delivering two authoritative batches.
  await page.clock.install({ time: new Date("2026-01-01T12:00:00Z") });
  await page.clock.pauseAt(new Date("2026-01-01T12:00:01Z"));
  await page.goto("/");
  await expect.poll(() => Boolean(stream)).toBe(true);
  await page.clock.runFor(32);
  const radar = page.getByTestId("radar");
  await radar.scrollIntoViewIfNeeded();
  await page.clock.runFor(100);
  const last = frame(8, point(35), { speed: 8 });
  last.world.agents.push({
    ...point(51),
    id: "CT1",
    team: "CT",
    name: "Atlas",
  });
  last.world.motion = {
    startTick: 0,
    tracks: {
      T1: Array.from({ length: 8 }, (_, i) => [51 - 2 * i, 15, Math.PI]),
      CT1: Array.from({ length: 8 }, (_, i) => [35 + 2 * i, 15, 0]),
    },
  };
  stream!.send(JSON.stringify(last));
  await expect(page.getByTestId("tick")).toHaveText("8");
  await page.clock.runFor(16);
  const hit = await page.evaluate(() => {
    const app = (window as any).testPixi;
    const marker = app.stage.getChildByLabel("CT1", true);
    const rect = app.canvas.getBoundingClientRect(),
      at = marker.getGlobalPosition();
    return { x: at.x + rect.x, y: at.y + rect.y, worldX: marker.x };
  });
  // Latest packet has T1 here. The drawn CT1 is still crossing from the left.
  expect(hit.worldX).toBeLessThan(42);
  if (hasTouch) await page.touchscreen.tap(hit.x, hit.y);
  else await page.mouse.click(hit.x, hit.y);
  await expect(page.getByRole("button", { name: /Atlas/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});
