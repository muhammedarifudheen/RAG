import { expect, test } from "@playwright/test";

import { ANSWER, HEALTH, HEALTH_RANKING, mockHealth } from "./fixtures";

// However long the server takes, the page never says it may be asleep: it shows the
// usual progress until the answer arrives. The page's clock is controlled here, so
// these tests do not wait that long.
const HINT = /wake up|waking|asleep|Still working/i;

test("a slow answer shows only its progress, never a waking-up hint", async ({ page }) => {
  await page.clock.install();
  let answer: () => void = () => {};
  const answered = new Promise<void>((resolve) => (answer = resolve));
  await page.route("**/api/ask", async (route) => {
    await answered;
    await route.fulfill({ json: ANSWER });
  });

  await page.goto("/chat");
  await page.getByLabel("Question").fill(ANSWER.question);
  await page.getByRole("button", { name: "Ask" }).click();

  const status = page.getByRole("status");
  await expect(status).toContainText("Searching the knowledge base and writing an answer…");
  await page.clock.runFor(90_000);
  await expect(status).toContainText("Searching the knowledge base and writing an answer…");
  await expect(page.getByText(HINT)).toHaveCount(0);

  answer();
  await expect(page.getByRole("article", { name: "Answer" })).toBeVisible();
  await expect(page.getByText(HINT)).toHaveCount(0);
});

test("a slow page load shows only its loading message", async ({ page }) => {
  await page.clock.install();
  let respond: () => void = () => {};
  const responded = new Promise<void>((resolve) => (respond = resolve));
  await mockHealth(page, HEALTH, HEALTH_RANKING);
  // Registered last, so it runs first: holds every health request back.
  await page.route("**/api/health*", async (route) => {
    await responded;
    await route.fallback();
  });

  await page.goto("/health");
  await expect(page.getByText("Computing code health…")).toBeVisible();
  await page.clock.runFor(90_000);
  await expect(page.getByText(HINT)).toHaveCount(0);

  respond();
  await expect(page.getByText("Computing code health…")).toHaveCount(0);
});
