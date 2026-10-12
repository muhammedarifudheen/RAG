import { expect, test, type Locator } from "@playwright/test";

import { EMPTY_HEALTH, HEALTH, HEALTH_RANKING, alerts, apiError, mockHealth } from "./fixtures";

const RED = "#dc2626";

function bars(chart: Locator): Locator {
  return chart.locator(".recharts-bar-rectangle path");
}

test("summarises dead code, cycles and long functions", async ({ page }) => {
  await mockHealth(page, HEALTH, HEALTH_RANKING);

  await page.goto("/health");

  await expect(page.getByRole("heading", { name: "Code health" })).toBeVisible();
  await expect(page.getByText("5 files, 18 symbols and 12 relationships analysed.")).toBeVisible();

  const summary = page.getByRole("region", { name: "Summary" });
  const stat = (label: string) => summary.locator("div").filter({ hasText: label }).locator("p").last();
  await expect(stat("Dead symbols")).toHaveText("4");
  await expect(stat("Circular dependencies")).toHaveText("2"); // one file cycle + one call cycle
  await expect(stat("Functions over 50 lines")).toHaveText("1");
  await expect(stat("Files with fan-out ≥ 10")).toHaveText("0");
});

test("charts complexity, flagging what crosses a threshold", async ({ page }) => {
  await mockHealth(page, HEALTH, HEALTH_RANKING);

  await page.goto("/health");

  // Longest functions: three bars, and only the 60-line one is over the 50-line threshold.
  const longest = page.getByTestId("chart-longest");
  await expect(bars(longest)).toHaveCount(3);
  await expect(longest).toContainText("long_job");
  await expect(longest).toContainText("format_name");
  await expect(longest.locator(`.recharts-bar-rectangle path[fill="${RED}"]`)).toHaveCount(1);
  await expect(longest.locator(".recharts-reference-line")).toHaveCount(1);

  // Fan-out: two files, neither near the threshold of 10.
  const fanOut = page.getByTestId("chart-fan-out");
  await expect(bars(fanOut)).toHaveCount(2);
  await expect(fanOut).toContainText("pkg/service.py");
  await expect(fanOut.locator(`.recharts-bar-rectangle path[fill="${RED}"]`)).toHaveCount(0);

  // Dead symbols by file: two files with two dead symbols each.
  const dead = page.getByTestId("chart-dead");
  await expect(bars(dead)).toHaveCount(2);
  await expect(dead).toContainText("pkg/models.py");
});

test("lists dead symbols and circular dependencies", async ({ page }) => {
  await mockHealth(page, HEALTH, HEALTH_RANKING);

  await page.goto("/health");

  const rows = page.getByRole("table", { name: "Dead symbols" }).locator("tbody tr");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(0)).toContainText("Base.describe");
  await expect(rows.nth(0)).toContainText("method");
  await expect(rows.nth(0)).toContainText("pkg/models.py:5-6");
  await expect(rows.nth(3)).toContainText("unused_helper");

  const cycles = page.getByRole("region", { name: "Circular dependencies" });
  await expect(cycles).toContainText("pkg/cycle_a.py ⇄ pkg/cycle_b.py");
  await expect(cycles).toContainText("ping (pkg/cycle_a.py) ⇄ pong (pkg/cycle_b.py)");
});

test("requests the report and the rankings separately", async ({ page }) => {
  const queries: string[] = [];
  await page.route("**/api/health*", (route) => {
    const url = new URL(route.request().url());
    queries.push(url.search);
    return route.fulfill({ json: url.searchParams.has("max_function_loc") ? HEALTH_RANKING : HEALTH });
  });

  await page.goto("/health");
  await expect(page.getByTestId("chart-longest")).toBeVisible();

  expect(queries.sort()).toEqual(["", "?max_function_loc=1&min_fan_out=1&limit=12"]);
});

test("explains an empty report and surfaces failures", async ({ page }) => {
  await mockHealth(page, EMPTY_HEALTH, EMPTY_HEALTH);
  await page.goto("/health");
  await expect(page.getByText("No repository has been ingested yet.")).toBeVisible();

  await page.unrouteAll();
  await page.route("**/api/health*", (route) => apiError(route, 503, "The database is unavailable."));
  await page.reload();
  await expect(alerts(page)).toHaveText("The database is unavailable.");
});
