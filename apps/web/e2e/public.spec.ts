import { expect, test } from "@playwright/test";

import { SOURCES, alerts, eventStream, mockConfig, mockSources } from "./fixtures";

const PASSWORD = "correct horse battery staple";

test.beforeEach(async ({ page }) => {
  await mockSources(page, SOURCES);
  // Registered after mockSources, so this public configuration takes precedence.
  await mockConfig(page, PASSWORD);
});

test("visitors of a public site can browse but not manage sources", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "This is a public Atlas" })).toBeVisible();
  await expect(page.getByLabel("Paste a link")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Upload a file" })).toHaveCount(0);

  // The knowledge base is listed, without Remove buttons.
  const list = page.getByRole("region", { name: "In the knowledge base" }).getByRole("listitem");
  await expect(list).toHaveCount(2);
  await expect(page.getByRole("button", { name: /^Remove/ })).toHaveCount(0);

  await page.getByRole("link", { name: "ask questions" }).click();
  await expect(page).toHaveURL(/\/chat\/?$/);
});

test("the admin unlocks with the password, and it is sent with changes", async ({ page }) => {
  let authorization: string | undefined;
  await page.route("**/api/ingest", (route) => {
    authorization = route.request().headers()["authorization"];
    return route.fulfill({
      contentType: "text/event-stream",
      body: eventStream([{ event: "done", data: { files: 1, symbols: 3, edges: 0 } }]),
    });
  });

  await page.goto("/");
  await page.getByLabel("Admin password").fill("not it");
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(alerts(page)).toHaveText("That is not the admin password.");
  await expect(page.getByLabel("Paste a link")).toHaveCount(0);

  await page.getByLabel("Admin password").fill(PASSWORD);
  await page.getByRole("button", { name: "Unlock" }).click();

  await expect(page.getByText("Signed in as admin.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove pallets/itsdangerous" })).toBeVisible();
  await page.getByLabel("Paste a link").fill("https://en.wikipedia.org/wiki/HMAC");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Ingested 1 files");
  expect(authorization).toBe(`Bearer ${PASSWORD}`);
});

test("the password is remembered in this browser until the admin locks", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Admin password").fill(PASSWORD);
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.getByText("Signed in as admin.")).toBeVisible();

  await page.reload();
  await expect(page.getByText("Signed in as admin.")).toBeVisible();

  await page.getByRole("button", { name: "Lock" }).click();
  await expect(page.getByRole("heading", { name: "This is a public Atlas" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "This is a public Atlas" })).toBeVisible();
});

test("a password changed on the server is forgotten", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => window.localStorage.setItem("atlas-admin-token", "an old password"));

  await page.reload();

  await expect(page.getByRole("heading", { name: "This is a public Atlas" })).toBeVisible();
  expect(await page.evaluate(() => window.localStorage.getItem("atlas-admin-token"))).toBeNull();
});
