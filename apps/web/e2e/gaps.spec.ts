import type { AskRequest, AskResponse, GapReport } from "@atlas/shared";
import { expect, test, type Page } from "@playwright/test";

import { mockSources } from "./fixtures";

// The gap finder: when the knowledge base falls short, the answer says what it is missing.

function reply(answer: string, extra: Partial<AskResponse> = {}): AskResponse {
  return {
    question: "How do Flask sessions work?",
    answer,
    citations: [],
    chunks: [],
    model: "none",
    complete: true,
    provider: "Atlas",
    route: "sources",
    suggestions: [],
    web_sources: [],
    ...extra,
  };
}

const GAPS: GapReport = {
  report:
    "1. **Covers well:** itsdangerous's signing.\n" +
    "2. **Missing:** Flask's session cookie.\n" +
    "3. **Best source to add:** https://github.com/pallets/flask",
  suggestion_url: "https://github.com/pallets/flask",
  found_by: "NVIDIA · nemotron",
};

async function mock(page: Page, answers: AskResponse[]): Promise<AskRequest[]> {
  const sent: AskRequest[] = [];
  await page.route("**/api/ask", (route) => {
    const body = route.request().postDataJSON() as AskRequest;
    sent.push(body);
    if (body.task === "gaps") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(reply(GAPS.report, { gaps: GAPS })),
      });
    }
    const next = answers.shift() ?? reply("…");
    return route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body:
        `event: route\ndata: ${JSON.stringify({ route: "sources", mode: "auto", providers: ["groq"] })}\n\n` +
        `event: done\ndata: ${JSON.stringify(next)}\n\n`,
    });
  });
  return sent;
}

test("when the knowledge base has nothing, the answer says what to add, and adding it is one click", async ({
  page,
}) => {
  await mockSources(page);
  const sent = await mock(page, [
    reply("I don't have that in the knowledge base."),
    reply("Sessions are signed cookies."),
  ]);
  await page.goto("/chat");
  await page.getByLabel("Question", { exact: true }).fill("How do Flask sessions work?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  const missing = page.getByRole("region", { name: "What's missing" });
  await expect(missing).toContainText("Flask's session cookie.");
  await expect(missing).toContainText("Found by NVIDIA · nemotron");
  expect(sent.filter((b) => b.task === "gaps").map((b) => b.question)).toEqual([
    "How do Flask sessions work?",
  ]);

  // An answer from the sources asks for nothing.
  await page.getByLabel("Question", { exact: true }).fill("And cookies?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByRole("article", { name: "Answer" }).nth(1)).toContainText("signed cookies");
  expect(sent.filter((b) => b.task === "gaps")).toHaveLength(1);

  await missing.getByRole("link", { name: "+ Add this source" }).click();
  await expect(page.getByLabel("Paste a link")).toHaveValue("https://github.com/pallets/flask");
});
