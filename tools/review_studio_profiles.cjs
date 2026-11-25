// Capture the active game's real profiles. The private facepack stays on the
// owner's server. Images are written only to the supplied local directory.
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("../frontend/node_modules/playwright");
const { portraits } = require("../backend/data/personal-portrait-sources.json");
const replacement = require("../backend/data/portrait-anatomy.json");

async function review(origin, output, all) {
  const players = Object.entries(portraits);
  const selection = all
    ? players
    : [
        players.find(([, p]) => p.name === "Chr1zN"),
        ...players.filter(([, p], i) => i % 8 === 2 && p.name !== "Chr1zN"),
      ].slice(0, 40);
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 960 },
    });
    await page.goto(origin);
    await page.getByRole("button", { name: "База сцены", exact: true }).click();
    for (const [id, player] of selection) {
      await page.getByLabel("Поиск", { exact: true }).fill(id);
      await page
        .locator(".db-list button")
        .filter({ has: page.getByText(player.name, { exact: true }) })
        .first()
        .click();
      const header = page.locator(".pf-heading");
      await header
        .locator(
          '[data-layer="appearance"][href*="' +
            replacement[player.sha256] +
            '"]',
        )
        .waitFor();
      await header
        .locator('[data-layer="kit"] [data-layer="fitted-fabric"]')
        .waitFor();
      await header.evaluate(async (element) => {
        await Promise.all(
          [...element.querySelectorAll("image")].map((node) => {
            const image = new Image();
            image.src = node.getAttribute("href");
            return image.decode();
          }),
        );
        await new Promise(requestAnimationFrame);
      });
      await header.screenshot({ path: path.join(output, id + ".png") });
    }
    console.log("Игровых профилей сохранено:", selection.length);
  } finally {
    await browser.close();
  }
}
const [origin, output, option] = process.argv.slice(2);
if (!origin || !output)
  throw new Error(
    "node tools/review_studio_profiles.cjs <URL игры> <каталог снимков> [--all]",
  );
review(origin, output, option === "--all").catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
