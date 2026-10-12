import type { IngestRequest } from "@atlas/shared";
import { expect, test } from "@playwright/test";

import { SOURCES, alerts, apiError, eventStream, mockSources } from "./fixtures";

const REPO = "https://github.com/pallets/itsdangerous";
const ARTICLE = "https://en.wikipedia.org/wiki/Alan_Turing";

const DOCUMENT_STREAM = eventStream([
  { event: "progress", data: { step: 1, total: 4, message: "Fetching the Wikipedia article 'Alan Turing'" } },
  { event: "progress", data: { step: 2, total: 4, message: "Splitting 1 document(s) into passages" } },
  { event: "progress", data: { step: null, total: null, message: "1 document(s), 41 passages" } },
  { event: "progress", data: { step: 3, total: 4, message: "Embedding 41 passages" } },
  { event: "progress", data: { step: 4, total: 4, message: "Writing to Postgres" } },
  { event: "done", data: { files: 1, symbols: 42, edges: 0 } },
]);

test("ingests a repository and streams its progress", async ({ page }) => {
  await mockSources(page);
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
  const input = page.getByLabel("Paste a link");
  // The original prompt for a repository URL is still what the field asks for first.
  await expect(input).toHaveAttribute("placeholder", /^Paste a GitHub repo URL/);
  await expect(page.getByRole("button", { name: "Add", exact: true })).toBeDisabled();

  await input.fill(REPO);
  await page.getByRole("button", { name: "Add", exact: true }).click();

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
  // No kind is sent: the server works it out from the link.
  expect(posted).toEqual({ url: REPO });

  await page.getByRole("link", { name: "Ask a question" }).click();
  await expect(page).toHaveURL(/\/chat$/);
});

test("adds a Wikipedia article and shows it in the knowledge base", async ({ page }) => {
  const sources = await mockSources(page, [SOURCES[1]]);
  let posted: IngestRequest | null = null;
  await page.route("**/api/ingest", (route) => {
    posted = route.request().postDataJSON() as IngestRequest;
    sources.unshift(SOURCES[0]); // what the server would now list
    return route.fulfill({ contentType: "text/event-stream", body: DOCUMENT_STREAM });
  });

  await page.goto("/");
  const list = page.getByRole("region", { name: "In the knowledge base" }).getByRole("listitem");
  await expect(list).toHaveCount(1);

  await page.getByLabel("Paste a link").fill(ARTICLE);
  await page.getByRole("button", { name: "Add", exact: true }).click();

  // Documents take four steps, not five; the list shows whatever the server reports.
  const steps = page.getByRole("list", { name: "Ingest progress" }).getByRole("listitem");
  await expect(steps).toHaveCount(4);
  await expect(steps.nth(1)).toContainText("1 document(s), 41 passages");
  await expect(steps.nth(3)).toContainText("4/4");
  expect(posted).toEqual({ url: ARTICLE });

  // The list reloads by itself and now holds both sources.
  await expect(list).toHaveCount(2);
  await expect(list.nth(0)).toContainText("Wikipedia");
  await expect(list.nth(0)).toContainText("Alan Turing (Wikipedia)");
  await expect(list.nth(0)).toContainText("1 file · 42 searchable items");
  await expect(list.nth(1)).toContainText("Repository");
  await expect(list.nth(1)).toContainText("15 files · 159 searchable items");
  await expect(list.nth(0).getByRole("link")).toHaveAttribute("href", ARTICLE);
});

test("a crawl sends its kind and page limit", async ({ page }) => {
  await mockSources(page);
  let posted: IngestRequest | null = null;
  await page.route("**/api/ingest", (route) => {
    posted = route.request().postDataJSON() as IngestRequest;
    return route.fulfill({ contentType: "text/event-stream", body: DOCUMENT_STREAM });
  });

  await page.goto("/");
  await expect(page.getByLabel("Maximum pages")).toHaveCount(0);
  await page.getByLabel("Paste a link").fill("https://docs.python.org/3/");
  await page.getByLabel("Follow links on the same site").check();
  await page.getByLabel("Maximum pages").fill("7");
  await page.getByRole("button", { name: "Add", exact: true }).click();

  await expect(page.getByRole("status")).toContainText("Ingested");
  expect(posted).toEqual({ url: "https://docs.python.org/3/", kind: "crawl", max_pages: 7 });
});

test("uploads a file", async ({ page }) => {
  await mockSources(page);
  let upload: { contentType: string; body: string } | null = null;
  await page.route("**/api/ingest/upload", (route) => {
    upload = {
      contentType: route.request().headers()["content-type"] ?? "",
      body: route.request().postData() ?? "",
    };
    return route.fulfill({ contentType: "text/event-stream", body: DOCUMENT_STREAM });
  });

  await page.goto("/");
  await expect(page.getByRole("button", { name: "Upload a file" })).toBeEnabled();
  await page.getByLabel("File to upload").setInputFiles({
    name: "notes.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Notes\n\nSignatures are compared in constant time.\n"),
  });

  await expect(page.getByRole("status")).toContainText("Ingested 1 files, 42 symbols and 0 edges.");
  expect(upload!.contentType).toMatch(/^multipart\/form-data; boundary=/);
  expect(upload!.body).toContain('name="file"; filename="notes.md"');
  expect(upload!.body).toContain("Signatures are compared in constant time.");
});

test("removes a source from the knowledge base", async ({ page }) => {
  await mockSources(page, SOURCES);

  await page.goto("/");
  const list = page.getByRole("region", { name: "In the knowledge base" }).getByRole("listitem");
  await expect(list).toHaveCount(2);

  await page.getByRole("button", { name: "Remove Alan Turing (Wikipedia)" }).click();

  await expect(list).toHaveCount(1);
  await expect(list.first()).toContainText("pallets/itsdangerous");

  await page.getByRole("button", { name: "Remove pallets/itsdangerous" }).click();
  await expect(page.getByText("Nothing yet. Add a link or a file above.")).toBeVisible();
});

test("shows the error that ended the stream", async ({ page }) => {
  await mockSources(page);
  await page.route("**/api/ingest", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: eventStream([
        { event: "progress", data: { step: 1, total: 4, message: "Fetching http://localhost/" } },
        { event: "error", data: { message: "That link points at a private or internal address." } },
      ]),
    }),
  );

  await page.goto("/");
  await page.getByLabel("Paste a link").fill("http://localhost/");
  await page.getByRole("button", { name: "Add", exact: true }).click();

  await expect(alerts(page)).toContainText("That link points at a private or internal address.");
  await expect(page.getByRole("list", { name: "Ingest progress" }).getByRole("listitem")).toHaveCount(1);
  // The form is usable again after a failure.
  await expect(page.getByRole("button", { name: "Add", exact: true })).toBeEnabled();
});

test("shows why a request was refused", async ({ page }) => {
  await mockSources(page);
  await page.route("**/api/ingest", (route) =>
    apiError(route, 409, "Another ingest is running; wait for it to finish."),
  );

  await page.goto("/");
  await page.getByLabel("Paste a link").fill(REPO);
  await page.getByRole("button", { name: "Add", exact: true }).click();

  await expect(alerts(page)).toHaveText("Another ingest is running; wait for it to finish.");
});

test("reports a stream that ends without a result", async ({ page }) => {
  await mockSources(page);
  await page.route("**/api/ingest", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: eventStream([{ event: "progress", data: { step: 1, total: 5, message: "Cloning" } }]),
    }),
  );

  await page.goto("/");
  await page.getByLabel("Paste a link").fill(REPO);
  await page.getByRole("button", { name: "Add", exact: true }).click();

  await expect(alerts(page)).toHaveText("The connection closed before ingestion finished.");
});
