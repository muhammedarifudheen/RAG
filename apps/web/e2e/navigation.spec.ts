import { expect, test } from "@playwright/test";

import { EMPTY_HEALTH, FILE_GRAPH, mockHealth } from "./fixtures";

test("the navigation reaches every page and marks the current one", async ({ page }) => {
  await page.route("**/api/graph/files", (route) => route.fulfill({ json: FILE_GRAPH }));
  await mockHealth(page, EMPTY_HEALTH, EMPTY_HEALTH);

  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Ingest" })).toHaveAttribute("aria-current", "page");

  await nav.getByRole("link", { name: "Chat" }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByRole("heading", { name: "Ask about the codebase" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Chat" })).toHaveAttribute("aria-current", "page");

  await nav.getByRole("link", { name: "Graph" }).click();
  await expect(page).toHaveURL(/\/graph$/);
  await expect(page.getByRole("heading", { name: "File dependencies" })).toBeVisible();

  await nav.getByRole("link", { name: "Health" }).click();
  await expect(page).toHaveURL(/\/health$/);
  await expect(nav.getByRole("link", { name: "Health" })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", { name: "Ingest" })).not.toHaveAttribute("aria-current", "page");
});
