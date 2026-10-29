import type { AskRequest, AskResponse, CodeChunk } from "@atlas/shared";
import { expect, test, type Page } from "@playwright/test";

// The relevance judge: its scores under the answer, and its switch and cut-off in Settings.

function excerpt(name: string, relevance: number, reason: string): CodeChunk {
  return {
    symbol_id: relevance,
    name,
    kind: "function",
    signature: null,
    file: "src/signer.py",
    language: "python",
    start_line: relevance * 10,
    end_line: relevance * 10 + 5,
    score: 0.61,
    snippet: "pass",
    snippet_end_line: relevance * 10 + 5,
    truncated: false,
    citation: `[src/signer.py:${relevance * 10}-${relevance * 10 + 5}]`,
    relevance,
    relevance_reason: reason,
  };
}

function reply(answer: string, extra: Partial<AskResponse> = {}): AskResponse {
  return {
    question: "q",
    answer,
    citations: [],
    chunks: [],
    model: "m",
    complete: true,
    provider: "Atlas council",
    route: "sources",
    suggestions: [],
    web_sources: [],
    ...extra,
  };
}

async function mock(page: Page, replies: AskResponse[]): Promise<AskRequest[]> {
  const sent: AskRequest[] = [];
  await page.route("**/api/ask", (route) => {
    sent.push(route.request().postDataJSON() as AskRequest);
    const next = replies.shift() ?? reply("…");
    return route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body:
        `event: judged\ndata: ${JSON.stringify(next.reranking ?? {})}\n\n` +
        `event: route\ndata: ${JSON.stringify({ route: "sources", mode: "auto", providers: ["groq"] })}\n\n` +
        `event: done\ndata: ${JSON.stringify(next)}\n\n`,
    });
  });
  return sent;
}

async function ask(page: Page, question: string) {
  await page.getByLabel("Question", { exact: true }).fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
}

test("the judge's scores are shown with the excerpts, and its cut-off can be changed or it turned off", async ({
  page,
}) => {
  const judged = reply("Answer.", {
    chunks: [
      excerpt("Signer.verify_signature", 9, "Compares the signatures."),
      excerpt("Signer.unsign", 7, "Calls the check."),
    ],
    reranking: { candidates: 16, judged: 15, kept: 2, cutoff: 4, ranked: true, top_pick: "It compares the signatures." },
  });
  const sent = await mock(page, [judged, reply("Stricter."), reply("Unjudged.")]);
  await page.goto("/chat");
  await ask(page, "How is a signature checked?");
  const answer = page.getByRole("article", { name: "Answer" });
  await answer.getByText(/2 code excerpts were given to m · the judge scored 15 of 16/).click();
  await expect(answer.getByText("relevance 9/10")).toBeVisible();
  await expect(answer.getByText("Compares the signatures.", { exact: true })).toBeVisible();
  await expect(answer).toContainText("then ranked them together");
  await expect(answer).toContainText("Top pick: It compares the signatures.");

  await page.getByRole("button", { name: "⚙ Settings" }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });
  await settings.getByRole("tab", { name: "Retrieval" }).click();
  await expect(settings.getByRole("switch", { name: /Judge each excerpt's relevance/ })).toBeChecked();
  await settings.getByLabel("Judge's cut-off").fill("7");
  await settings.getByRole("button", { name: "Close settings" }).click();
  await ask(page, "Only the best?");
  await expect(page.getByRole("article", { name: "Answer" }).nth(1)).toContainText("Stricter.");

  await page.getByRole("button", { name: "⚙ Settings" }).click();
  await settings.getByRole("tab", { name: "Retrieval" }).click();
  await settings.getByRole("switch", { name: /Then rank the kept excerpts/ }).uncheck();
  await settings.getByRole("switch", { name: /Judge each excerpt's relevance/ }).uncheck();
  await settings.getByRole("button", { name: "Close settings" }).click();
  await ask(page, "No judge?");
  await expect(page.getByRole("article", { name: "Answer" }).nth(2)).toContainText("Unjudged.");

  expect(sent[0].rerank).toBeUndefined();
  expect(sent[0].rerank_cutoff).toBeUndefined();
  expect(sent[1].rerank_cutoff).toBe(7);
  expect(sent[1].rank_passages).toBeUndefined();
  expect(sent[2].rerank).toBe(false);
  expect(sent[2].rank_passages).toBe(false);
});
