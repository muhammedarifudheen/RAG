import type { AskResponse, Webhook } from "@atlas/shared";
import { expect, test } from "@playwright/test";

import { mockSources } from "./fixtures";

// Integrations: the OpenAI and MCP addresses, webhooks (secret shown once), Word and code
// uploads, and Wikipedia's licence beside its excerpts.

test("the admin adds a webhook and sees its secret once, beside the other integrations", async ({
  page,
}) => {
  await mockSources(page, []);
  const hooks: Webhook[] = [];
  const added: unknown[] = [];
  await page.route("**/api/webhooks", (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as { url: string; events: Webhook["events"] };
      added.push(body);
      const hook: Webhook = { id: 1, url: body.url, events: body.events, last_status: null };
      hooks.push(hook);
      return route.fulfill({ status: 201, json: { ...hook, secret: "whsec_abc" } });
    }
    return route.fulfill({ json: hooks });
  });

  await page.goto("/");
  const section = page.getByRole("region", { name: "Integrations" });
  await expect(section).toContainText("/v1");
  await expect(section).toContainText("/mcp");
  await expect(section).toContainText("/hooks/github");
  await expect(page.getByLabel("File to upload")).toHaveAttribute("accept", /\.docx.*\.py.*\.go/);

  await page.getByLabel("Webhook address").fill("https://hooks.example.com/atlas");
  await section.getByLabel("Answers").uncheck();
  await section.getByRole("button", { name: "Add webhook" }).click();
  await expect(section.getByLabel("Webhook secret")).toHaveText("whsec_abc");
  await expect(section.getByRole("list", { name: "Webhooks" })).toContainText(
    "https://hooks.example.com/atlas",
  );
  expect(added).toEqual([
    { url: "https://hooks.example.com/atlas", events: ["ingest", "gap", "health"] },
  ]);
});

test("a Wikipedia excerpt is credited with its licence", async ({ page }) => {
  const answer: AskResponse = {
    question: "What is HMAC?",
    answer: "A keyed hash [wikipedia/HMAC:1-2].",
    citations: [],
    chunks: [
      {
        symbol_id: 9,
        name: "HMAC",
        kind: "section",
        signature: null,
        file: "wikipedia/HMAC",
        language: "markdown",
        start_line: 1,
        end_line: 2,
        score: 0.8,
        snippet: "HMAC is a keyed hash.",
        snippet_end_line: 2,
        truncated: false,
        citation: "[wikipedia/HMAC:1-2]",
        license: "CC BY-SA 4.0",
        source_url: "https://en.wikipedia.org/wiki/HMAC",
        source_title: "HMAC (Wikipedia)",
      },
    ],
    model: "m",
    complete: true,
    provider: "Atlas council",
    route: "sources",
    suggestions: [],
    web_sources: [],
    epistemic: "known",
    footer: "[confidence: KNOWN] [sources: 1] [license: CC BY-SA 4.0]",
  };
  await page.route("**/api/ask", (route) =>
    route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body:
        `event: route\ndata: ${JSON.stringify({ route: "sources", mode: "auto", providers: ["groq"] })}\n\n` +
        `event: done\ndata: ${JSON.stringify(answer)}\n\n`,
    }),
  );
  await page.goto("/chat");
  await page.getByLabel("Question", { exact: true }).fill("What is HMAC?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const shown = page.getByRole("article", { name: "Answer" });
  await expect(shown.getByLabel("Answer footer")).toContainText("[license: CC BY-SA 4.0]");
  await shown.getByText("Sources used").click();
  const credit = shown.getByLabel("Attribution");
  await expect(credit).toContainText("From HMAC (Wikipedia), licensed CC BY-SA 4.0");
  await expect(credit.getByRole("link", { name: "HMAC (Wikipedia)" })).toHaveAttribute(
    "href",
    "https://en.wikipedia.org/wiki/HMAC",
  );
});
