import type { IngestRequest } from "@atlas/shared";
import { expect, test } from "@playwright/test";

import { alerts, apiError, eventStream } from "./fixtures";

const REPO = "https://github.com/pallets/itsdangerous";

test("ingests a repository and streams its progress", async ({ page }) => {
  let posted: IngestRequest | null = null;
  await page.route("**/api/ingest", (route) => {
    posted = route.request().postDataJSON() as IngestRequest;
    return route.fulfill({
      contentType: "text/event-stream",
      body: eventStream([
        { event: "progress", data: { step: 1, total: 5, message: `Cloning ${REPO}` } },
        { event: "progress", data: { step: null, total: null, message: "/tmp/atlas-x at 672971d66a2e" } },
        { event: "progress", data: { step: 2, total: 5, message: "Parsing source files" } },
        { event: "progress", data: { step: null, total: null, message: "7 files (3 python), 38 symbols" } },
        { event: "progress", data: { step: 3, total: 5, message: "Resolving imports, calls and inheritance" } },
        { event: "progress", data: { step: 4, total: 5, message: "Embedding 38 symbols" } },
        { event: "progress", data: { step: 5, total: 5, message: "Writing to Postgres" } },
        { event: "done", data: { files: 7, symbols: 38, edges: 29 } },
      ]),
    });
  });

  await page.goto("/");
  const input = page.getByLabel("Paste a GitHub repo URL");
  await expect(input).toHaveAttribute("placeholder", "Paste a GitHub repo URL");
  await expect(page.getByRole("button", { name: "Ingest" })).toBeDisabled();

  await input.fill(REPO);
  await page.getByRole("button", { name: "Ingest" }).click();

  const steps = page.getByRole("list", { name: "Ingest progress" }).getByRole("listitem");
  await expect(steps).toHaveCount(5);
  await expect(steps.nth(0)).toContainText(`Cloning ${REPO}`);
  await expect(steps.nth(0)).toContainText("/tmp/atlas-x at 672971d66a2e");
  await expect(steps.nth(1)).toContainText("Parsing source files");
  await expect(steps.nth(1)).toContainText("7 files (3 python), 38 symbols");
  await expect(steps.nth(4)).toContainText("Writing to Postgres");
  await expect(steps.nth(4)).toContainText("5/5");

  await expect(page.getByRole("status")).toContainText(
    "Ingested 7 files, 38 symbols and 29 edges.",
  );
  expect(posted).toEqual({ repo_url: REPO });

  await page.getByRole("link", { name: "Ask a question" }).click();
  await expect(page).toHaveURL(/\/chat$/);
});

test("shows the error that ended the stream", async ({ page }) => {
  await page.route("**/api/ingest", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: eventStream([
        { event: "progress", data: { step: 1, total: 5, message: `Cloning ${REPO}` } },
        { event: "error", data: { message: "Database is not ready: connection timeout expired" } },
      ]),
    }),
  );

  await page.goto("/");
  await page.getByLabel("Paste a GitHub repo URL").fill(REPO);
  await page.getByRole("button", { name: "Ingest" }).click();

  await expect(alerts(page)).toContainText(
    "Database is not ready: connection timeout expired",
  );
  await expect(page.getByRole("list", { name: "Ingest progress" }).getByRole("listitem")).toHaveCount(1);
  // The form is usable again after a failure.
  await expect(page.getByRole("button", { name: "Ingest" })).toBeEnabled();
});

test("shows why a request was refused", async ({ page }) => {
  await page.route("**/api/ingest", (route) =>
    apiError(route, 409, "Another ingest is running; wait for it to finish."),
  );

  await page.goto("/");
  await page.getByLabel("Paste a GitHub repo URL").fill(REPO);
  await page.getByRole("button", { name: "Ingest" }).click();

  await expect(alerts(page)).toHaveText(
    "Another ingest is running; wait for it to finish.",
  );
});

test("reports a stream that ends without a result", async ({ page }) => {
  await page.route("**/api/ingest", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: eventStream([{ event: "progress", data: { step: 1, total: 5, message: "Cloning" } }]),
    }),
  );

  await page.goto("/");
  await page.getByLabel("Paste a GitHub repo URL").fill(REPO);
  await page.getByRole("button", { name: "Ingest" }).click();

  await expect(alerts(page)).toHaveText(
    "The connection closed before ingestion finished.",
  );
});
