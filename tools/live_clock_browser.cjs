// Manual probe of the production bundle. Observe the actual radar paint clock without
// shipping a debug API or changing the production build. The probe fails on an unmatched hook.
const fs = require("node:fs");
const { chromium } = require("../frontend/node_modules/playwright");
(async () => {
  const [port, result, peerCount] = process.argv.slice(2);
  const browser = await chromium.launch({
    executablePath:
      process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || "/usr/bin/chromium",
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1280, height: 800 },
    });
    await page.addInitScript(() => {
      window.clockProbe = { packets: [], renders: [], throws: {}, sprites: {} };
      const p = window.clockProbe;
      let airborne = [];
      window.measureSprite = (kind, x, y, fallback = false) => {
        const item = airborne.find(
          (e) => e.kind === kind && Math.hypot(e.x - x, e.y - y) < 1e-5,
        );
        if (!item) return;
        const at = epoch();
        const f = (p.sprites[item.id] ??= {
          start: item.start,
          land: item.land,
          kind,
          first: at,
          last: at,
          count: 0,
        });
        f.last = at;
        f.count++;
        if (fallback) f.fallback = (f.fallback || 0) + 1;
      };
      const epoch = () => performance.timeOrigin + performance.now();
      window.measurePaint = (tick, match) => {
        const at = epoch();
        p.renders.push([at, tick]);
        airborne = [];
        if (!p.hud || at - p.hud.at(-1)[0] >= 250)
          (p.hud ??= []).push([
            at,
            document.querySelector(".round-clock")?.textContent,
          ]);
        for (const e of match.effects) {
          if (tick < e.start || tick >= e.land) continue;
          const id = e.player + "/" + e.start;
          const flight = (p.throws[id] ??= {
            start: e.start,
            land: e.land,
            kind: e.kind,
            first: at,
            last: at,
            count: 0,
          });
          flight.last = at;
          flight.count++;
          const t = tick - e.start,
            path = e.trajectory;
          const a = path?.[Math.min(path.length - 1, Math.floor(t))],
            b = path?.[Math.min(path.length - 1, Math.floor(t) + 1)];
          const ratio = t / (e.land - e.start);
          airborne.push({
            kind: e.kind,
            start: e.start,
            land: e.land,
            id,
            x: a ? a[0] + (b[0] - a[0]) * (t % 1) : e.sx + (e.x - e.sx) * ratio,
            y: a ? a[1] + (b[1] - a[1]) * (t % 1) : e.sy + (e.y - e.sy) * ratio,
          });
        }
        return tick;
      };
      const Native = window.WebSocket;
      window.connectSpectators = (count) =>
        Promise.all(
          Array.from(
            { length: count },
            (_, i) =>
              new Promise((resolve, reject) => {
                const socket = new Native(
                  "ws://" +
                    location.host +
                    "/api/stream?view=" +
                    ["T", "CT", "full"][i % 3],
                );
                (window.spectators ??= []).push(socket);
                socket.addEventListener("message", resolve, { once: true });
                socket.addEventListener("error", reject, { once: true });
              }),
          ),
        ).then(() => true);
      window.WebSocket = class extends Native {
        constructor(...args) {
          super(...args);
          this.addEventListener("message", (e) => {
            const at = epoch();
            const world = JSON.parse(e.data).world;
            const parseMs = epoch() - at;
            p.packets.push([
              at,
              world.tick,
              world.time,
              world.match?.clock,
              world.match?.round,
              parseMs,
              e.data.length,
              world.match?.phase,
            ]);
            if (world.tick <= 610) {
              (p.poses ??= []).push([
                at,
                world.tick,
                world.map.id,
                world.agents
                  .filter((a) => a.alive)
                  .map((a) => [a.id, a.x, a.y, a.z, a.weapon, a.status]),
              ]);
            }
          });
        }
      };
    });
    const textureDelay = Number(process.env.CLOCK_TEXTURE_DELAY_MS || 0);
    if (textureDelay)
      await page.route(
        /\/scorebot\/(hegrenade|flashbang|smokegrenade|decoy|incgrenade|molotov)\.svg$/,
        async (route) => {
          await new Promise((resolve) => setTimeout(resolve, textureDelay));
          await route.continue();
        },
      );
    await page.route("**/assets/index-*.js", async (route) => {
      const response = await route.fetch();
      const src = await response.text();
      const hook =
        /(const (\w+)=(\w+)\.frame\.world\.match;if\(\2\)\{const \w+=)(\w+\.displayTick\(\w+\))/;
      if (!hook.test(src))
        throw Error("Radar paint call not found in the production bundle");
      const sprite =
        /(show\((\w+),(\w+),(\w+),\w+,\w+,\w+,\w+\)\{[^}]*?const [\s\S]{0,1000}?\+\+this\.used,[^}]+?\.visible=!0)(\}(?:airborne|end)\()/;
      if (!sprite.test(src))
        throw Error(
          "Radar sprite paint call not found in the production bundle",
        );
      const fallback =
        /(airborne\(\w+,(\w+),(\w+),(\w+),[^}]+?this\.used===\w+&&)([^}]+?\.fill\(\w+\))(\})/;
      if (src.includes(".airborne(") && !fallback.test(src))
        throw Error("Missing cold texture paint hook");
      await route.fulfill({
        response,
        body: src
          .replace(hook, "$1window.measurePaint($4,$2)")
          .replace(sprite, "$1,window.measureSprite($2,$3,$4)$5")
          .replace(fallback, "$1($5,window.measureSprite($2,$3,$4,true))$6"),
      });
    });
    const base = "http://127.0.0.1:" + port;
    await page.goto(base + "/?screen=lab");
    await page.getByTestId("radar").waitFor();
    await page.waitForFunction(() => window.clockProbe.renders.length > 0);
    if (peerCount)
      await page.evaluate(
        (n) => window.connectSpectators(n),
        Number(peerCount),
      );
    await page.getByRole("button", { name: "Запустить", exact: true }).click();
    await page.waitForFunction(() => {
      const a = window.clockProbe.packets;
      return a.length > 3 && a.at(-1)[1] >= a[0][1] + 2;
    });
    const start = await page.evaluate(
      () => performance.timeOrigin + performance.now(),
    );
    await page.waitForTimeout(60000);
    // Keep a sample on each side of the fixed window, even with slow readers.
    await page.waitForFunction(
      (end) =>
        window.clockProbe.packets.at(-1)[0] > end &&
        window.clockProbe.renders.at(-1)[0] > end,
      start + 60000,
    );
    const data = await page.evaluate(() => window.clockProbe);
    fs.writeFileSync(result, JSON.stringify({ start, ...data }));
  } finally {
    await browser.close();
  }
})().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
