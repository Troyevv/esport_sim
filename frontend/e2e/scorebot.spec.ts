import { expect, test } from "@playwright/test";

test("Scorebot показывает установленную C4, обе пятёрки и счёт их команд", async ({
  page,
}, info) => {
  await page.goto("/?screen=lab");
  const command = async (kind: string, value?: unknown) => {
    const response = await page.evaluate(
      async ({ kind, value }) => {
        const state = await (await fetch("/api/state")).json();
        const result = await fetch("/api/command", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id: crypto.randomUUID(),
            revision: state.revision,
            context: state.context,
            kind,
            value,
          }),
        });
        return { ok: result.ok, text: await result.text() };
      },
      { kind, value },
    );
    expect(response.ok, response.text).toBe(true);
  };
  const { package: pack } = await (
    await page.request.get("/api/database/scene-20261125-clubs/1")
  ).json();
  const rosters = ["Team Spirit", "Team Vitality"].map((name) =>
    Object.keys(pack.rosters).find((id) => pack.rosters[id].name === name),
  );
  const state = await (await page.request.get("/api/state")).json();
  await command(state.careerId ? "career-exhibition" : "database-match", {
    id: pack.id,
    revision: 1,
    rosters,
    seed: 4,
  });
  await expect(page.locator(".hud-team")).toHaveCount(2);
  await expect(page.locator(".player-card")).toHaveCount(10);
  await expect(page.getByTestId("radar")).toHaveAttribute("data-ready", "true");
  await command("speed", 8);
  await command("start");
  await expect(page.locator(".hud-history")).toBeVisible({ timeout: 25000 });
  await expect(page.locator(".hud-bomb")).toBeVisible({ timeout: 25000 });
  await command("speed", 1);
  const planted = await (await page.request.get("/api/state")).json();
  expect(planted.running).toBe(true);
  for (const club of planted.world.match.clubs) {
    const team = page
      .locator(".hud-team")
      .filter({
        has: page.getByRole("heading", { name: new RegExp(club.name) }),
      });
    await expect(team.getByRole("meter")).toHaveCount(5);
    await expect(team).toHaveAttribute("data-side", club.side);
    await expect(
      page.locator('.scoreboard [data-team="' + club.id + '"] > b'),
    ).toHaveText(String(club.score));
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.locator(".scoreboard").scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("r33-scorebot-" + info.project.name + ".png"),
    fullPage: true,
  });
  await command("pause");
  await page.getByLabel("Режим обзора").selectOption("T");
  await expect(page.locator('.hud-team[data-side="CT"] .hud-kit')).toHaveText(
    Array(5).fill("Снаряжение —"),
  );
  await command("reset", 42);
});
