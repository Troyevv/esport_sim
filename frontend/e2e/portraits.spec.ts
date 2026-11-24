import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";

test("Ноябрьский срез, доступный флаг и клубная форма", async ({
  page,
}, info) => {
  await page.goto("/");
  await page.getByRole("button", { name: "База сцены", exact: true }).click();
  await expect(page.getByLabel("Пакет и редакция")).toHaveValue(
    "scene-20261124/1",
  );
  await page.getByLabel("Поиск", { exact: true }).fill("ZywOo");
  await page.locator(".db-list").getByRole("button", { name: /ZywOo/ }).click();
  await expect(page.locator(".pf-heading")).toContainText("Mathieu Herbaut");
  await expect(
    page
      .locator(".pf-heading")
      .getByRole("img", { name: "Франция", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".pf-heading .game-portrait")).toHaveAccessibleName(
    /Team Vitality/,
  );
  await expect(
    page.getByText("Rating 3.0", { exact: true }).first(),
  ).toBeVisible();
  await page.getByText("Примерочная формы", { exact: true }).click();
  await page.getByLabel("Комплект формы").selectOption({ label: "Astralis" });
  await expect(
    page.locator(".kit-preview .game-portrait"),
  ).toHaveAccessibleName(/Astralis/);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.locator(".kit-preview").scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("scene-november.png") });
});

test("Одна внешность в двух командах и у свободного агента", async ({
  page,
}, info) => {
  await page.goto("/");
  await page.getByRole("button", { name: "База сцены", exact: true }).click();
  const pack = (
    await (await page.request.get("/api/database/austin-registration/1")).json()
  ).package;
  const seasonal = (
    await (await page.request.get("/api/database/scene-20261124/1")).json()
  ).package;
  for (const [k, team] of Object.entries(seasonal.teams) as [string, any][]) {
    if (team.name === "Astralis")
      pack.teams[k] = {
        name: team.name,
        fields: {},
        origin: "model",
        organization: null,
        region: team.region,
        tier: team.tier,
        logo: team.logo,
      };
  }
  pack.id = "portrait-pilot-" + info.project.name;
  pack.title = "Проверка внешности · демонстрационные персонажи";
  const roster = Object.values(pack.rosters).find(
    (r: any) => r.name === "Vitality",
  ) as { players: string[]; team: string };
  const pids = roster.players.slice(0, 2);
  const heads = pids.map((pid, i) => {
    const bytes = readFileSync(
      resolve("e2e/fixtures/portraits/model-" + (i ? "b" : "a") + ".png"),
    );
    const image = "data:image/png;base64," + bytes.toString("base64");
    Object.assign(pack.players[pid], {
      name: "Модель " + (i ? "Б" : "А"),
      photo: null,
      realName: null,
      nationality: null,
      appearance: {
        image,
        author: "EsportSim · демонстрационная внешность",
        source: "https://github.com/Troyevv/esport_sim",
        license: "CC0",
        changes: "Синтетический пример, выделены голова и шея",
      },
    });
    return image;
  });
  // Python and JS emit the same canonical ordering for this JSON document.
  const canonical = (v: any): any =>
    Array.isArray(v)
      ? v.map(canonical)
      : v && typeof v === "object"
        ? Object.fromEntries(
            Object.keys(v)
              .sort()
              .map((k) => [k, canonical(v[k])]),
          )
        : v;
  const sha256 = createHash("sha256")
    .update(JSON.stringify(canonical(pack)))
    .digest("hex");
  await page.getByLabel("Файл пакета").setInputFiles({
    name: "pilot.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ package: pack, sha256 })),
  });
  await expect(page.getByLabel("Пакет и редакция")).toHaveValue(pack.id + "/1");
  for (const [i, pid] of pids.entries()) {
    await page
      .getByLabel("Поиск", { exact: true })
      .fill(pack.players[pid].name);
    await page
      .locator(".db-list")
      .getByRole("button", { name: new RegExp(pack.players[pid].name) })
      .click();
    const lab = page.locator(".kit-studio");
    if (
      !(await lab.getAttribute("open")) &&
      !(await lab.locator("select").isVisible())
    )
      await lab.locator("summary").click();
    const portrait = lab.locator(".game-portrait");
    for (const [key, label] of [
      ["first", "Vitality"],
      ["second", "Astralis"],
      ["free", "Свободный агент"],
    ]) {
      await lab.locator("select").selectOption({ label });
      await expect(
        portrait.locator('[data-layer="appearance"]'),
      ).toHaveAttribute("href", heads[i]);
      await expect(portrait).toHaveAccessibleName(
        new RegExp(key === "free" ? "нейтральная" : label),
      );
      if (info.project.name === "desktop")
        await portrait.screenshot({
          path: info.outputPath("pilot-" + i + "-" + key + ".png"),
          omitBackground: true,
        });
    }
  }
  // Change the real roster records in a new revision through the same API
  // used by the editor; the profile must re-resolve its kit on reload.
  const pairs = Object.entries(pack.rosters) as [
    string,
    { name: string; players: string[] },
  ][];
  const [oldId, old] = pairs.find(([, r]) => r.name === "Vitality")!;
  const [newId, next] = pairs.find(([, r]) => r.name === "Falcons")!;
  const pid = pids[0];
  for (const [j, [rid, record]] of [
    [
      oldId,
      { ...old, captain: null, players: old.players.filter((x) => x !== pid) },
    ],
    [
      newId,
      { ...next, captain: null, players: [pid, ...next.players.slice(1)] },
    ],
  ].entries()) {
    const res = await page.request.post(
      "/api/database/" + pack.id + "/" + (j + 1) + "/rosters/" + rid,
      {
        headers: { Origin: new URL(page.url()).origin },
        data: { create: false, record },
      },
    );
    expect(res.ok(), await res.text()).toBeTruthy();
  }
  await page.reload();
  await page.getByRole("button", { name: "База сцены", exact: true }).click();
  await page.getByLabel("Пакет и редакция").selectOption(pack.id + "/3");
  await page.getByLabel("Поиск", { exact: true }).fill("Модель А");
  await page
    .locator(".db-list")
    .getByRole("button", { name: /Модель А/ })
    .click();
  await expect(page.locator(".pf-heading .game-portrait")).toHaveAccessibleName(
    /Falcons/,
  );
  await expect(
    page.locator('.pf-heading [data-layer="appearance"]'),
  ).toHaveAttribute("href", heads[0]);
});

test("Однокнопочный импорт сохраняет уже подготовленную внешность", async ({
  page,
}, info) => {
  await page.goto("/");
  await page.getByRole("button", { name: "База сцены", exact: true }).click();
  const { package: p } = await (
    await page.request.get("/api/database/austin-registration/1")
  ).json();
  const [pid, r] = Object.entries(p.players)[0] as [string, any];
  const bytes = readFileSync(resolve("e2e/fixtures/portraits/model-a.png"));
  r.appearance = {
    image: "data:image/png;base64," + bytes.toString("base64"),
    author: "EsportSim",
    source: "https://github.com/Troyevv/esport_sim",
    license: "CC0",
    changes: "Тестовая модель",
  };
  Object.assign(p, {
    id: "studio-ready-" + info.project.name,
    title: "Готовая внешность · пилот",
    players: { [pid]: r },
    rosters: {},
    teams: {},
    organizations: {},
    history: {},
    staff: {},
  });
  const ordered = (v: any): any =>
    Array.isArray(v)
      ? v.map(ordered)
      : v && typeof v === "object"
        ? Object.fromEntries(
            Object.keys(v)
              .sort()
              .map((k) => [k, ordered(v[k])]),
          )
        : v;
  const sha256 = createHash("sha256")
    .update(JSON.stringify(ordered(p)))
    .digest("hex");
  await page
    .getByLabel("Файл пакета")
    .setInputFiles({
      name: "studio.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify({ package: p, sha256 })),
    });
  await expect(page.getByLabel("Пакет и редакция")).toHaveValue(p.id + "/1");
  await page.getByText("Студийные портреты", { exact: true }).click();
  await page.getByRole("button", { name: "Пилот · 3 игрока" }).click();
  await expect(page.locator(".db-import-studio")).toContainText("Завершено", {
    timeout: 16000,
  });
  await expect(
    page.locator('.pf-heading [data-layer="appearance"]'),
  ).toHaveAttribute("href", r.appearance.image);
  if (info.project.name === "phone-portrait")
    await page
      .locator(".db-import-studio")
      .screenshot({ path: info.outputPath("studio-import.png") });
});
