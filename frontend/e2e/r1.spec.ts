import { test, expect } from "@playwright/test";
import { touchCamera } from "./touchCamera";

test("полный BO1, колл, сохранение и итог матча", async ({
  page,
  hasTouch,
}, info) => {
  test.setTimeout(150_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const button = (name: string) =>
    page.getByRole("button", { name, exact: true });
  const press = async (name: string) => {
    if (hasTouch) await button(name).tap();
    else await button(name).click();
  };
  if ((await (await page.request.get("/api/state")).json()).careerId) {
    await page.goto("/");
    await page.getByRole("button", {name: "Стенд симуляции", exact: true}).click();
  } else await page.goto("/?screen=lab");
  await expect(page.getByTestId("connection")).toContainText("На связи");
  const seed = 7171 + info.project.name.length;
  // All suites use the same home server. Enter the real lab before choosing this match.
  const snapshot = await (await page.request.get("/api/state")).json();
  if (snapshot.world.match) {
    await page.getByText("Новый сценарий", { exact: true }).click();
    await press("Стенд R0");
  }
  await page.getByLabel("Seed", { exact: true }).fill(String(seed));
  await press("Открыть матч BO1");
  await expect(page.locator(".scoreboard")).toContainText("РАУНД 1");
  await expect(page.getByTestId("radar")).toHaveAttribute("data-ready", "true");
  await expect(page.locator(".lineups")).toContainText(/Север.*OVR/s);
  if (await page.locator(".touch-lineup").isVisible()) await press("Север");
  await page.getByRole("button", { name: /Sable/ }).click();
  if (await page.locator(".touch-lineup").isVisible()) await press("Радар");
  await expect(page.locator(".role-ratings")).toContainText(/Рифлер.*Снайпер.*Капитан/);
  await page.screenshot({ path: info.outputPath("r31-ratings.png"), fullPage: true });
  if (hasTouch) {
    await touchCamera(page);
    await press("Центрировать карту");
  }
  await press("8×");
  await press("Запустить");
  await expect(page.locator(".round-clock")).toContainText("В игре");
  await press("Запросить тайм-аут");
  await expect(page.locator(".round-clock")).toContainText("ПАУЗА", {
    timeout: 25_000,
  });
  await expect(page.locator(".coaching blockquote").first()).toBeVisible();
  const room = page.getByRole("region", { name: "Тактический перерыв" });
  await expect(room.locator(".bench-five button")).toHaveCount(5);
  await room.locator(".bench-five button").nth(1).click();
  await room.getByLabel("Обращение", {exact:true}).selectOption("opinion");
  await press("Обратиться · 10 с");
  await expect(room.locator(".round-clock")).toContainText("50 с");
  await expect(room.locator("details[open] blockquote")).toHaveCount(1);
  await expect(room.locator("svg.game-portrait")).toHaveCount(5);
  await page.screenshot({path: info.outputPath("timeout-" + info.project.name + ".png"),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.getByLabel("План на ближайший раунд").selectOption("Выход B");
  await press("Передать колл");
  await expect(
    page.getByRole("status").filter({ hasText: "Принято" }),
  ).toContainText("Выход B");
  await press("Сохранить");
  await page.reload();
  await expect(page.locator(".round-clock")).toContainText("ПАУЗА");
  await expect(page.locator(".coaching")).toContainText("2 / 3");
  await press("Загрузить");
  await press("Завершить тайм-аут");
  await expect(page.locator(".round-clock")).toContainText("В игре");
  await page.waitForTimeout(1100);
  await press("Пауза просмотра");
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(1);
  await page.screenshot({
    path: info.outputPath("bo1-" + info.project.name + ".png"),
    fullPage: true,
  });
  for (const view of ["CT", "T", "full"]) {
    await page.getByLabel("Режим обзора").selectOption(view);
    await expect(page.getByTestId("connection")).toContainText("На связи");
  }
  await press("Статистика");
  await expect(page.locator("tbody tr")).toHaveCount(10);
  await press("Быстро");
  await press("Запустить");
  await expect(page.locator(".match-result")).toContainText("Победитель", {
    timeout: 85_000,
  });
  await press("Раунды");
  const final = await (await page.request.get("/api/state")).json();
  await expect(page.locator(".round-list > div")).toHaveCount(
    final.world.match.score.reduce((a: number, b: number) => a + b, 0),
  );
  console.log(
    "BO1",
    seed,
    final.world.match.score,
    final.world.match.history.map((r: { reason: string }) => r.reason),
  );
  await expect(button("Запросить тайм-аут")).toBeDisabled();
  expect(errors).toEqual([]);
  await page.getByText("Новый сценарий", { exact: true }).click();
  await press("Стенд R0");
});

test(
  "потеря ответа о тайм-ауте и состояние второго устройства",
  { tag: "@receipts" },
  async ({ page, browser }, info) => {
    const peer = await browser.newContext({
      baseURL: info.project.use.baseURL,
    });
    try {
      if ((await (await page.request.get("/api/state")).json()).careerId) {
    await page.goto("/");
    await page.getByRole("button", {name: "Стенд симуляции", exact: true}).click();
  } else await page.goto("/?screen=lab");
      await page.getByRole("button", { name: "Открыть матч BO1" }).click();
      let id = "";
      await page.route(
        "**/api/command",
        async (route) => {
          id = route.request().postDataJSON().id;
          expect((await route.fetch()).ok()).toBeTruthy();
          await route.abort("connectionreset");
        },
        { times: 1 },
      );
      await page.getByRole("button", { name: "Запросить тайм-аут" }).click();
      await expect(page.locator(".coaching")).toContainText("2 / 3");
      const second = await peer.newPage();
      await second.goto("/?screen=lab");
      await expect(second.locator(".coaching")).toContainText("2 / 3");
      expect(
        (await second.request.get("/api/command/" + id)).ok(),
      ).toBeTruthy();
      await second.getByRole("button", { name: "Завершить тайм-аут" }).click();
      await expect(
        page.getByRole("button", { name: "Передать колл" }),
      ).toHaveCount(0);
      await page.getByText("Новый сценарий", { exact: true }).click();
      await page.getByRole("button", { name: "Стенд R0" }).click();
    } finally {
      await peer.close();
    }
  },
);

test("ошибка чтения сохранения останавливает повторы и допускает ручное подключение", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/state?view=*", route => {
    attempts++;
    return route.fulfill({ status: 500, body: "Internal Server Error" });
  });
  if ((await (await page.request.get("/api/state")).json()).careerId) {
    await page.goto("/");
    await page.getByRole("button", {name: "Стенд симуляции", exact: true}).click();
  } else await page.goto("/?screen=lab");
  await expect(page.getByRole("alert")).toContainText("HTTP 500");
  await expect(page.getByTestId("connection")).toHaveText("Ошибка загрузки");
  const failedAttempts = attempts;
  await page.waitForTimeout(1000);
  expect(attempts).toBe(failedAttempts);
  await page.unroute("**/api/state?view=*");
  await page.getByRole("button", { name: "Повторить подключение" }).click();
  await expect(page.getByTestId("connection")).toHaveText("На связи");
});
