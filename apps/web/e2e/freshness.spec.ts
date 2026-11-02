import type { AskResponse } from "@atlas/shared";
import { expect, test } from "@playwright/test";

// The 100x answer: TL;DR, detail, action; a freshness chip; an older conflicting source
// folded away under "Previous version".

test("an answer leads with its TL;DR, ends with an action, and shows its freshness", async ({
  page,
}) => {
  const answer: AskResponse = {
    question: "How long is a token valid?",
    answer:
      "⚠ This may be outdated — last ingested 2026-06-01.\n\n" +
      "**TL;DR:** 30 days by default [docs/tokens.md:3-5].\n\n" +
      "The `max_age` argument sets it [docs/tokens.md:3-5].\n\n" +
      "**Action:** pass `max_age` explicitly.\n\n" +
      "Gotcha: seconds, not days.\n\n" +
      "Previous version:\nIt used to be 7 days [docs/old.md:1-2].",
    citations: [],
    chunks: [],
    model: "m",
    complete: true,
    provider: "Atlas council",
    route: "sources",
    suggestions: [],
    web_sources: [],
    epistemic: "known",
    freshness: { label: "stale", ingested_at: "2026-06-01T10:00:00Z" },
    footer: "[confidence: KNOWN] [freshness: STALE] [sources: 2] [latency: 900ms]",
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
  await page.getByLabel("Question", { exact: true }).fill("How long is a token valid?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const shown = page.getByRole("article", { name: "Answer" });
  await expect(shown.getByRole("note", { name: /Freshness: stale, last ingested 2026-06-01/ })).toBeVisible();
  await expect(shown.locator('[data-callout="stale"]')).toContainText("This may be outdated");
  await expect(shown.locator('[data-callout="tldr"]')).toContainText("30 days by default");
  await expect(shown.locator('[data-callout="action"]')).toContainText("pass max_age explicitly");
  await expect(shown.locator('[data-callout="gotcha"]')).toContainText("seconds, not days");
  // The older source is folded away until opened.
  const older = shown.locator("details", { hasText: "Previous version" });
  await expect(older.getByText("It used to be 7 days")).toBeHidden();
  await older.locator("summary").click();
  await expect(older.getByText("It used to be 7 days")).toBeVisible();
  await expect(shown.getByLabel("Answer footer")).toContainText("[freshness: STALE]");
});
