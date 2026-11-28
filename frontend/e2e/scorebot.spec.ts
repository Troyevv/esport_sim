import { openLab } from "./openLab";
import { expect, test } from "@playwright/test";

test("Scorebot показывает установленную C4, обе пятёрки и счёт их команд", async ({
  page,
}, info) => {
  await openLab(page);
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
  await expect(page.locator(".mx-live-roster")).toHaveCount(2);
  await expect(page.locator(".mx-live-player")).toHaveCount(10);
  await expect(page.getByTestId("radar")).toHaveAttribute("data-ready", "true");
  await expect(page.locator(".mx-live-weapon [data-item=Glock]")).toHaveCount(5);
  await expect(page.locator(".mx-live-weapon [data-item=USP]")).toHaveCount(5);
  await expect(page.locator(".mx-live-weapon [data-item=AK-47]")).toHaveCount(0);
  await expect(page.locator(".carried-c4")).toHaveCount(1);
  await command("speed", 8);
  await command("start");
  await expect(page.locator(".mx-round-timeline")).toBeVisible({ timeout: 25000 });
  await expect(page.locator(".hud-bomb")).toBeVisible({ timeout: 25000 });
  await command("speed", 1);
  const planted = await (await page.request.get("/api/state")).json();
  expect(planted.running).toBe(true);
  for (const club of planted.world.match.clubs) {
    const team=page.locator('.mx-live-roster[data-team="'+club.id+'"]');
    await expect(team.getByRole("meter")).toHaveCount(5);
    await expect(team).toHaveAttribute("data-side", club.side);
    await expect(
      page.locator('.mx-broadcast-score [data-team="' + club.id + '"] > b'),
    ).toHaveText(String(club.score));
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.locator(".mx-broadcast-score").scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("r33-scorebot-" + info.project.name + ".png"),
    fullPage: true,
  });
  await command("pause");
  const paused = (await (await page.request.get("/api/state")).json()).world;
  for (const player of paused.agents) {
    const card = page.locator('[data-player="' + player.id + '"]');
    await card.click();
    for (const [slot, model] of [
      ["primary-gun", player.primary],
      ["secondary", player.secondary],
    ]) {
      const img = page.locator(".selected-loadout ." + slot + " img");
      if (model) await expect(img).toHaveAttribute("data-item", model);
      else await expect(img).toHaveCount(0);
    }
    await page.locator(".mx-match-tabs").getByRole("button",{name:"Радар",exact:true}).click();
    if (player.alive) {
      for (const utility of new Set<string>(player.utility)) {
        const count = player.utility.filter(
          (g: string) => g === utility,
        ).length;
        await expect(
          card.locator('.hud-kit [data-item="' + utility + '"]'),
        ).toHaveAttribute("alt", new RegExp("×" + count + "$"));
      }
    }
  }
  expect(paused.match.kills.length).toBeGreaterThan(0);
  for (const kill of paused.match.kills) {
    const row = page.locator('[data-kill="' + kill.id + '"]');
    await expect(row.locator(".kill-weapon")).toHaveAttribute(
      "data-item",
      kill.weapon,
    );
    await expect(row.locator('[data-item="В голову"]')).toHaveCount(
      Number(kill.head),
    );
    await expect(row.locator('[data-item="Помощь"]')).toHaveCount(
      Number(kill.assists.length > 0),
    );
  }
  expect(
    await page.locator(".sb-icon").evaluateAll(async (icons) => {
      await Promise.all(
        icons.map((icon) => (icon as HTMLImageElement).decode()),
      );
      return icons.every((icon) => (icon as HTMLImageElement).naturalWidth > 0);
    }),
  ).toBe(true);
  const selected = paused.agents.find(
    (a: { alive: boolean; primary: string }) => a.alive && a.primary,
  );
  const card = page.locator('[data-player="' + selected.id + '"]');
  if (info.project.use.hasTouch) await card.tap();
  else await card.click();
  await expect(
    page.locator(".selected-loadout .primary-gun img"),
  ).toHaveAttribute("data-item", selected.primary);
  await page.locator(".mx-match-tabs").getByRole("button",{name:"Радар",exact:true}).click();
  await page.getByLabel("Режим обзора").selectOption("T");
  await expect(page.locator('.mx-live-roster[data-side="CT"] .mx-knowledge-hint')).toHaveText(
    Array(5).fill(/Экипировка неизвестна|Устранение подтверждено/),
  );
  await page.getByLabel("Режим обзора").selectOption("full");
  await command("speed", 128);
  await command("start");
  const firstAttack = planted.world.match.clubs.find(
    (c: { side: string }) => c.side === "T",
  );
  await expect(
    page.locator('.mx-broadcast-score [data-team="' + firstAttack.id + '"]'),
  ).toHaveAttribute("data-side", "CT");
  await expect(page.locator(".match-result")).toBeVisible({ timeout: 30000 });
  const final = (await (await page.request.get("/api/state")).json()).world
    .match;
  const winner = final.clubs.find(
    (club: { id: string }) => club.id === final.winnerTeamId,
  );
  await expect(page.locator(".match-result strong").first()).toHaveText(winner.name);
  for (const club of final.clubs) {
    const wins = final.history.filter(
      (r: { winnerTeamId: string }) => r.winnerTeamId === club.id,
    ).length;
    await expect(
      page.locator('.mx-broadcast-score [data-team="' + club.id + '"] > b'),
    ).toHaveText(String(wins));
  }
  await command("reset", 42);
});
