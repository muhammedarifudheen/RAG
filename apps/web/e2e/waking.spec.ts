import { expect, test } from "@playwright/test";

import { ANSWER, HEALTH, HEALTH_RANKING, mockHealth } from "./fixtures";

// The public server sleeps when idle and takes about a minute to wake. The
// page's clock is controlled here, so these tests do not wait that long.
const HINT = /its server takes about a minute to wake up/;

test("a slow answer says the server may be waking up, and the answer still arrives", async ({
  page,
}) => {
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
  await expect(status).not.toContainText(HINT);

  await page.clock.runFor(13_000);
  await expect(status).toContainText(HINT);

  answer();
  await expect(page.getByRole("article", { name: "Answer" })).toBeVisible();
  await expect(page.getByText(HINT)).toHaveCount(0);
});

test("a quick answer shows no waking-up hint", async ({ page }) => {
  await page.clock.install();
  await page.route("**/api/ask", (route) => route.fulfill({ json: ANSWER }));

  await page.goto("/chat");
  await page.getByLabel("Question").fill(ANSWER.question);
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByRole("article", { name: "Answer" })).toBeVisible();

  await page.clock.runFor(13_000);
  await expect(page.getByText(HINT)).toHaveCount(0);
});

test("a slow page load says the server may be waking up", async ({ page }) => {
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
  await page.clock.runFor(13_000);
  await expect(page.getByText(HINT)).toBeVisible();

  respond();
  await expect(page.getByText(HINT)).toHaveCount(0);
});
