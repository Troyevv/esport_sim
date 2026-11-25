import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import type { Application, Container } from "pixi.js";
import type { Frame } from "../src/session";

type Positions = [number, number, number][];
type Arrival = { at: number; tick: number; poses: Positions };
type Refresh = { at: number; renders: number; cost: number; poses: Positions };
type Probe = {
  app?: Application;
  renders: number;
  cost: number;
  refreshes: Refresh[];
  packets: Arrival[];
  sampling: boolean;
};
declare global {
  interface Window {
    motionProbe: Probe;
  }
}

test.use({
  trace: "off",
  deviceScaleFactor: async ({ hasTouch }, use) => use(hasTouch ? 2 : 1),
});

function distribution(numbers: number[]) {
  const sorted = [...numbers].sort((a, b) => a - b);
  const q = (p: number) =>
    Number(sorted[Math.floor((sorted.length - 1) * p)]?.toFixed(3));
  return {
    p05: q(0.05),
    median: q(0.5),
    p95: q(0.95),
    p99: q(0.99),
    max: q(1),
  };
}
const intervals = (rows: { at: number }[]) =>
  rows.slice(1).map((r, i) => r.at - rows[i].at);
function analyze(refreshes: Refresh[], packets: Arrival[], speed: number) {
  let holds = 0,
    jumps = 0,
    renders = 0,
    longestHoldMs = 0,
    holdMs = 0;
  const velocities: number[] = [],
    turns: number[] = [];
  for (let i = 1; i < refreshes.length; i++) {
    const a = refreshes[i - 1],
      b = refreshes[i],
      dt = b.at - a.at;
    const strides = b.poses.map(([x, y, h], j) => {
      const old = a.poses[j];
      const dh = h - old[2];
      turns.push(
        (Math.abs(Math.atan2(Math.sin(dh), Math.cos(dh))) * 180) / Math.PI,
      );
      return Math.hypot(x - old[0], y - old[1]);
    });
    // Fastest of ten agents excludes an individual stopping or rounding a corner.
    const ratio = Math.max(...strides) / (dt * speed * 0.02);
    velocities.push(ratio);
    if (ratio < 0.05) {
      holds++;
      holdMs += dt;
      longestHoldMs = Math.max(holdMs, longestHoldMs);
    } else holdMs = 0;
    if (ratio > 1.8) jumps++;
    if (a.renders !== b.renders) renders++;
  }
  const time = (refreshes.at(-1)!.at - refreshes[0].at) / 1000;
  return {
    refreshFPS: (refreshes.length - 1) / time,
    drawnFPS: renders / time,
    frameMs: distribution(intervals(refreshes)),
    renderCallMs: distribution(refreshes.map((r) => r.cost)),
    packetMs: distribution(intervals(packets)),
    strideRatio: distribution(velocities),
    headingDeltaDeg: distribution(turns),
    holds,
    jumps,
    longestHoldMs,
  };
}

test("доставка снимков, движение за кадр и видеозапись радара", async ({
  page,
}, info) => {
  test.skip(!["desktop", "phone-portrait"].includes(info.project.name));
  test.setTimeout(90000);
  let jitter = false,
    number = 0;
  const incoming: number[] = [];
  await page.routeWebSocket("**/api/stream**", (socket) => {
    const upstream = socket.connectToServer();
    const held: (string | Buffer)[] = [];
    let timer: ReturnType<typeof setTimeout> | undefined;
    socket.onClose(() => {
      clearTimeout(timer);
      upstream.close();
    });
    upstream.onMessage((data) => {
      const now = performance.now();
      incoming.push(now);
      // Preserve TCP ordering and every real server message. Delayed packets
      // catch up in a burst after a 215 ms head-of-line delay every 1.2 s.
      const delay = jitter && number++ % 12 === 5;
      if (timer || delay) {
        held.push(data);
        if (!timer)
          timer = setTimeout(() => {
            for (const message of held.splice(0)) socket.send(message);
            timer = undefined;
          }, 215);
      } else socket.send(data);
    });
  });
  await page.addInitScript(() => {
    const probe: Probe = {
      renders: 0,
      cost: 0,
      refreshes: [],
      packets: [],
      sampling: false,
    };
    window.motionProbe = probe;
    const nativeRAF = window.requestAnimationFrame.bind(window);
    let presentationTime = 0;
    window.requestAnimationFrame = (callback) =>
      nativeRAF((at) => {
        presentationTime = at;
        callback(at);
      });
    const Native = window.WebSocket;
    window.WebSocket = class extends Native {
      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols);
        this.addEventListener("message", (e) => {
          if (!probe.sampling) return;
          const f: Frame = JSON.parse(e.data);
          probe.packets.push({
            at: performance.now(),
            tick: f.world.tick,
            poses: f.world.agents.map((a) => [a.x, a.y, a.heading]),
          });
        });
      }
    };
    Object.assign(window, {
      __PIXI_APP_INIT__: (app: Application) => {
        probe.app = app;
        const render = app.render.bind(app);
        app.render = () => {
          const before = performance.now();
          render();
          probe.renders++;
          probe.cost = performance.now() - before;
          // Both RAF callbacks share a vsync timestamp. Match the image to that
          // refresh even when the observer callback runs before Pixi's callback.
          if (
            probe.sampling &&
            probe.refreshes.at(-1)?.at === presentationTime
          ) {
            probe.refreshes.pop();
            record(presentationTime);
          }
        };
      },
    });
    function record(at: number) {
      const players = probe.app?.stage.getChildByLabel("players", true);
      if (probe.sampling && players?.children.length) {
        const poses = players.children.map(
          (m: Container) =>
            [m.x, m.y, m.children[0].rotation] as [number, number, number],
        );
        probe.refreshes.push({
          at,
          renders: probe.renders,
          cost: probe.cost,
          poses,
        });
      }
    }
    function observe(at: number) {
      record(at);
      requestAnimationFrame(observe);
    }
    requestAnimationFrame(observe);
  });
  await page.goto("/?screen=lab");
  await expect(page.getByTestId("radar")).toHaveAttribute("data-ready", "true");
  const control = (name: string) =>
    page.getByRole("button", { name, exact: true });
  if (await control("Пауза").count()) await control("Пауза").click();
  await page.getByLabel("Seed", { exact: true }).fill("42");
  await control("Сбросить").click();
  await expect(page.getByTestId("tick")).toHaveText("0");
  await control("1×").click();
  await control("Запустить").click();
  const reports = [];
  for (const [condition, speed] of [
    ["loopback", 1],
    ["loopback", 8],
    ["jitter", 1],
    ["jitter", 4],
    ["jitter", 8],
  ] as const) {
    jitter = condition === "jitter";
    await control(speed + "×").click();
    await page.getByTestId("radar").scrollIntoViewIfNeeded();
    await page.waitForTimeout(650);
    incoming.length = 0;
    const data = await page.evaluate(async () => {
      const p = window.motionProbe;
      p.refreshes = [];
      p.packets = [];
      p.sampling = true;
      await new Promise((r) => setTimeout(r, 4200));
      p.sampling = false;
      return { frames: p.refreshes, packets: p.packets };
    });
    const ticks = data.packets.map((p) => p.tick);
    expect(ticks).toEqual([...ticks].sort((a, b) => a - b));
    const result = {
      condition,
      speed,
      upstreamMs: distribution(intervals(incoming.map((at) => ({ at })))),
      ...analyze(data.frames, data.packets, speed),
    };
    reports.push(result);
    console.log("MOTION", info.project.name, JSON.stringify(result));
    await writeFile(
      info.outputPath(condition + "-" + speed + "x.json"),
      JSON.stringify(data),
    );
  }
  await writeFile(
    info.outputPath("motion-summary.json"),
    JSON.stringify(reports, null, 2),
  );

  // Separate pass: record the actual game canvas; the encoder never runs during timing samples.
  if (info.project.name === "desktop") {
    await control("Пауза").click();
    await control("Сбросить").click();
    await expect(page.getByTestId("tick")).toHaveText("0");
    await control("1×").click();
    await control("Запустить").click();
    await page.getByTestId("radar").scrollIntoViewIfNeeded();
    const clip = page.evaluate(async () => {
      const canvas = window.motionProbe.app!.canvas as HTMLCanvasElement;
      const stream = canvas.captureStream(60);
      const rec = new MediaRecorder(stream, {
        mimeType: "video/webm;codecs=vp8",
        videoBitsPerSecond: 4500000,
      });
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      const stopped = new Promise<void>(
        (resolve) => (rec.onstop = () => resolve()),
      );
      rec.start();
      await new Promise((r) => setTimeout(r, 10000));
      rec.stop();
      await stopped;
      stream.getTracks().forEach((t) => t.stop());
      const reader = new FileReader();
      const data = new Promise<string>(
        (resolve) =>
          (reader.onload = () => resolve(String(reader.result).split(",")[1])),
      );
      reader.readAsDataURL(new Blob(chunks));
      return await data;
    });
    await page.waitForTimeout(5000);
    await control("4×").click();
    const path = info.outputPath("radar-motion.webm");
    await writeFile(path, Buffer.from(await clip, "base64"));
    await info.attach("Видео движения 1× и 4× с джиттером", {
      path,
      contentType: "video/webm",
    });
  }
  await control("Пауза").click();
  for (const report of reports) {
    // Catch a scene that submits on every refresh but repeats poses and then
    // teleports. Hardware-dependent timing is kept in the evidence alongside it.
    expect(report.strideRatio.p05).toBeGreaterThan(0.2);
    expect(report.strideRatio.p95).toBeLessThan(1.45);
  }
});
