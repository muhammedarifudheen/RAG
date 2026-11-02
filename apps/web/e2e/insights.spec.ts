import type { AnalyticsResult, AskResponse } from "@atlas/shared";
import { expect, test } from "@playwright/test";

// Analytics: the Insights page (top questions, failing, gaps, slowest, sources, drift,
// feedback, with CSV), thumbs on answers, and a chat saved as PDF with footnotes.

function result(metric: AnalyticsResult["metric"], rows: Record<string, unknown>[]): AnalyticsResult {
  return { metric, window: 7, rows };
}

const RESULTS: Record<string, AnalyticsResult> = {
  top_questions: result("top_questions", [{ question: "How does unsign work?", count: 5 }]),
  failing: result("failing", [{ question: "What is the tagline?", why: "thumbs down: wrong", state: "absent" }]),
  gaps: result("gaps", [{ question: "Is SHA1 safe?", count: 3, state: "absent", suggestion: "https://www.rfc-editor.org/rfc/rfc6194" }]),
  slowest: result("slowest", [{ question: "Trace a request", latency_ms: 24000, mode: "AGENT" }]),
  sources: result("sources", [{ source: "pallets/itsdangerous", retrieved: 9, cited: 7, precision: 0.78 }]),
  feedback: result("feedback", [{ question: "What is the tagline?", rating: "down", reason: "wrong" }]),
  drift: result("drift", [
    { week: "2026-W44", answers: 10, hit_rate: 0.6, latency_ms: 9000, faithfulness: 0.8, approval: 0.5 },
    {
      week: "2026-W45", answers: 12, hit_rate: 0.75, latency_ms: 8000, faithfulness: 0.7, approval: 0.6,
      change: { hit_rate: 0.15, latency_ms: -1000, faithfulness: -0.1, approval: 0.1 },
    },
  ]),
};

test("the insights page shows each surface, drift with its direction, and exports CSV", async ({ page }) => {
  await page.route("**/api/analytics?*", (route) => {
    const metric = new URL(route.request().url()).searchParams.get("metric")!;
    return route.fulfill({ json: RESULTS[metric] });
  });
  await page.route("**/api/export/analytics.csv*", (route) =>
    route.fulfill({ status: 200, contentType: "text/csv", body: "question,why\nq,thumbs down" }),
  );
  await page.goto("/insights");
  await expect(page.getByRole("heading", { name: "Insights", level: 1 })).toBeVisible();
  await expect(page.getByRole("region", { name: "Failing questions" })).toContainText("thumbs down: wrong");
  await expect(page.getByRole("region", { name: "Top gaps" }).getByRole("link", { name: "+ add" })).toHaveAttribute(
    "href",
    /\?add=https%3A%2F%2Fwww\.rfc-editor\.org/,
  );
  const drift = page.getByRole("region", { name: "Drift, week over week" });
  await expect(drift).toContainText("▲ 0.15 better");
  await expect(drift).toContainText("▼ 1000 better"); // lower latency is better
  await expect(drift).toContainText("▼ 0.1 worse");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Failing questions as CSV" }).click();
  expect((await download).suggestedFilename()).toBe("atlas-failing.csv");
});

test("an answer can be rated, a thumbs down with a reason", async ({ page }) => {
  const answer: AskResponse = {
    question: "What signs a value?",
    answer: "TL;DR: Signer.sign.",
    citations: [],
    chunks: [],
    model: "m",
    complete: true,
    provider: "Atlas council",
    route: "sources",
    suggestions: [],
    web_sources: [],
    footer: "[confidence: KNOWN] [freshness: FRESH] [sources: 1] [latency: 900ms]",
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
  const rated: unknown[] = [];
  await page.route("**/api/feedback", (route) => {
    rated.push(route.request().postDataJSON());
    return route.fulfill({ status: 204 });
  });
  await page.goto("/chat");
  await page.getByLabel("Question", { exact: true }).fill("What signs a value?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const shown = page.getByRole("article", { name: "Answer" });
  await shown.getByRole("button", { name: "Not helpful" }).click();
  await shown.getByLabel("What was wrong?").fill("missing the salt");
  await shown.getByRole("button", { name: "Send" }).click();
  await expect(shown.getByRole("status")).toContainText("Thanks");
  expect(rated).toEqual([{ question: "What signs a value?", rating: "down", reason: "missing the salt" }]);
  await expect(page.getByRole("button", { name: "PDF" })).toBeEnabled();
});
