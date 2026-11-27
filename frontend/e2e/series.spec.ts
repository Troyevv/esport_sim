import { expect, test } from "@playwright/test";

if (process.env.ESPORT_CS2_QA) {
  test("Вето BO5, ручной бан, капитан, восстановление и подготовка карты", async ({
    page,
    hasTouch,
  }, info) => {
    test.setTimeout(120000);
    const button = (name: string) =>
      page.getByRole("button", { name, exact: true });
    const press = async (name: string) => {
      if (hasTouch) await button(name).tap();
      else await button(name).click();
    };
    const capture = async (name: string) => {
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: info.outputPath(name + ".png"),
        fullPage: true,
      });
    };
    await page.goto("/");
    await press("Стенд симуляции");
    await expect(page.getByText("Лаборатория симуляции", { exact: true })).toBeVisible();
    // Reopening this URL later must restore the lab rather than the main menu.
    await page.goto("/?screen=lab");
    await expect(page.getByTestId("connection")).toContainText("На связи");
    if ((await (await page.request.get("/api/state")).json()).world.match) {
      await page.getByText("Новый сценарий", { exact: true }).click();
      await press("Стенд R0");
    }
    await page.getByLabel("Seed", { exact: true }).fill("42");
    await page.getByLabel("Формат матча").selectOption("5");
    await press("Начать вето BO5");
    await expect(page.locator(".veto-card")).toHaveCount(7);
    await expect
      .poll(() =>
        page
          .locator(".veto-art img")
          .evaluateAll((imgs) =>
            imgs.every((el) => (el as HTMLImageElement).naturalWidth > 0),
          ),
      )
      .toBeTruthy();
    await capture("veto");
    const option = page.locator(".veto-select").first();
    if (hasTouch) await option.tap();
    else await option.click();
    await press(
      (await button("Забанить карту").isVisible())
        ? "Забанить карту"
        : "Подтвердить бан",
    );
    await press("Сохранить");
    await page.reload();
    await expect(page.locator(".veto-card[data-state=ban]")).toHaveCount(2);
    if (hasTouch) await option.tap();
    else await option.click();
    await press(
      (await button("Пикнуть карту").isVisible())
        ? "Пикнуть карту"
        : "Подтвердить пик",
    );
    await press("Атака · T");
    await page.getByText("Делегировать оставшиеся ходы").click();
    await press("Капитану");
    await expect(page.locator(".series-order li")).toHaveCount(5);
    await press("Загрузить");
    await expect(page.locator(".veto-select").first()).toBeVisible();
    if (!(await button("Штабу").isVisible()))
      await page.getByText("Делегировать оставшиеся ходы").click();
    await press("Штабу");
    await capture("order");
    await press("Перейти к подготовке");
    await expect(page.getByTestId("radar")).toHaveAttribute(
      "data-ready",
      "true",
    );
    await page
      .getByText("Статистика игроков за серию", { exact: true })
      .click();
    await expect(page.locator(".series-stat-grid tbody tr")).toHaveCount(10);
    await capture("match");
    if (info.project.name === "phone-portrait") {
      test.setTimeout(240000);
      await press("Быстро");
      await press("Запустить");
      const next = page.getByRole("button", { name: /Подготовка к карте 2/ });
      await expect(next).toBeVisible({ timeout: 160000 });
      await press("Сохранить");
      await page.reload();
      await expect(next).toBeVisible();
      await capture("interval");
      await next.tap();
      await expect(page.getByTestId("radar")).toHaveAttribute(
        "data-ready",
        "true",
      );
      await press("Выбрать тактику");
      await expect(page.getByTestId("tactic-map")).toHaveAttribute(
        "data-ready",
        "true",
      );
      await capture("preparation");
    }
  });
}
