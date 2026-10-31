import type { AskResponse, SourceItem } from "@atlas/shared";
import { expect, test } from "@playwright/test";

import { mockSources } from "./fixtures";

// Source weights: primary 3, secondary 2, derived 1; shown with sources and answers.

const SOURCES: SourceItem[] = [
  {
    id: 2,
    kind: "wikipedia",
    title: "HMAC (Wikipedia)",
    url: "https://en.wikipedia.org/wiki/HMAC",
    created_at: "2026-10-30T10:00:00Z",
    files: 1,
    symbols: 15,
    weight: 2,
    weight_override: null,
  },
];

test("the admin sets how much a source counts", async ({ page }) => {
  const sources = await mockSources(page, SOURCES);
  const patched: unknown[] = [];
  await page.route("**/api/sources/2", (route) => {
    const body = route.request().postDataJSON() as { weight: number | null };
    patched.push(body);
    sources[0] = { ...sources[0], weight: body.weight ?? 2, weight_override: body.weight };
    return route.fulfill({ json: sources[0] });
  });
  await page.goto("/");
  const weight = page.getByLabel("Weight of HMAC (Wikipedia)");
  await expect(weight).toHaveValue("0");
  await expect(weight.locator("option").first()).toHaveText("Auto: Secondary");
  await weight.selectOption("3");
  await expect(weight).toHaveValue("3");
  expect(patched).toEqual([{ weight: 3 }]);
});

test("an answer on secondary sources says so, and each excerpt shows its weight", async ({
  page,
}) => {
  const answer: AskResponse = {
    question: "When was HMAC published?",
    answer: "This is based on secondary sources only.\n\nIn 1996 [wikipedia/HMAC:3-5].",
    citations: [],
    chunks: [
      {
        symbol_id: 9,
        name: "History",
        kind: "section",
        signature: null,
        file: "wikipedia/HMAC",
        language: "markdown",
        start_line: 3,
        end_line: 5,
        score: 0.6,
        snippet: "HMAC was published in 1996.",
        snippet_end_line: 5,
        truncated: false,
        citation: "[wikipedia/HMAC:3-5]",
        weight: 2,
      },
    ],
    model: "m",
    complete: true,
    provider: "Atlas council",
    route: "sources",
    suggestions: [],
    web_sources: [],
    epistemic: "known",
    source_basis: "secondary",
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
  await page.getByLabel("Question", { exact: true }).fill("When was HMAC published?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const shown = page.getByRole("article", { name: "Answer" });
  await expect(shown.getByRole("note", { name: /Based on secondary sources only/ })).toBeVisible();
  await expect(shown).toContainText("This is based on secondary sources only.");
  await shown.getByText("Sources used").click();
  await expect(shown.locator("details li").first()).toContainText("secondary · 2");
});
