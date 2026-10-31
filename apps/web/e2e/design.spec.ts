import type { AskRequest, AskResponse, CodeChunk } from "@atlas/shared";
import { expect, test, type Page } from "@playwright/test";

// Confidence, the sources used, copying a citation, the answer cache, high contrast.

function excerpt(symbol_id: number, name: string, start: number): CodeChunk {
  return {
    symbol_id,
    name,
    kind: "method",
    signature: null,
    file: "src/signer.py",
    language: "python",
    start_line: start,
    end_line: start + 9,
    score: 0.71,
    snippet: `def ${name}(self):\n    first line\n    second line\n    hidden line`,
    snippet_end_line: start + 9,
    truncated: false,
    citation: `[src/signer.py:${start}-${start + 9}]`,
  };
}

function reply(answer: string, extra: Partial<AskResponse> = {}): AskResponse {
  return {
    question: "How is a signature checked?",
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

async function mock(page: Page, answers: AskResponse[]): Promise<{ bodies: AskRequest[]; fresh: string[] }> {
  const bodies: AskRequest[] = [];
  const fresh: string[] = [];
  await page.route("**/api/ask", (route) => {
    bodies.push(route.request().postDataJSON() as AskRequest);
    fresh.push(route.request().headers()["x-atlas-fresh"] ?? "");
    const next = answers.shift() ?? reply("…");
    return route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body:
        `event: route\ndata: ${JSON.stringify({ route: "sources", mode: "auto", providers: ["groq"] })}\n\n` +
        `event: done\ndata: ${JSON.stringify(next)}\n\n`,
    });
  });
  return { bodies, fresh };
}

async function ask(page: Page, question: string) {
  await page.getByLabel("Question", { exact: true }).fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
}

test("an answer shows its confidence and the sources it used, cited first, each copyable", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await mock(page, [
    reply("It compares in constant time [src/signer.py:220-229].", {
      chunks: [excerpt(1, "get_signature", 100), excerpt(2, "verify_signature", 220)],
      citations: [
        { ref: "[src/signer.py:220-229]", file: "src/signer.py", start_line: 220, end_line: 229, verified: true },
      ],
      confidence: {
        level: "high",
        relevance: 0.9,
        coverage: 1,
        verified: 1,
        citations: 1,
        reason: "excerpt relevance 90%, 100% of sentences cited, 1 of 1 citations checked",
      },
      timings: { search: 0.12, judge: 2.4, answer: 6.8 },
      notice: "Retrieval failed, so this answer used keyword search.",
    }),
  ]);
  await page.goto("/chat");
  await ask(page, "How is a signature checked?");
  const answer = page.getByRole("article", { name: "Answer" });

  await expect(answer.getByRole("note", { name: /High confidence/ })).toBeVisible();
  await expect(answer).toContainText("Retrieval failed, so this answer used keyword search.");
  await expect(answer.getByRole("button", { name: /src\/signer\.py:220-229: citation/ })).toBeVisible();

  await answer.getByText("Sources used").click();
  await expect(answer).toContainText("search 0.1 s · judge 2.4 s · answer 6.8 s");
  const sources = answer.locator("details li");
  await expect(sources.first()).toContainText("verify_signature"); // the cited one first
  await expect(sources.first()).toContainText("cited");
  await expect(sources.first()).toContainText("first line");
  await expect(sources.first()).not.toContainText("hidden line"); // three lines of each

  await answer.getByRole("button", { name: "Copy the citation of verify_signature" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("[src/signer.py:220-229]");
});

test("a repeated answer says so, and regenerating asks afresh", async ({ page }) => {
  const sent = await mock(page, [reply("Stored.", { cached: true }), reply("Fresh.")]);
  await page.goto("/chat");
  await ask(page, "How is a signature checked?");
  await expect(page.getByRole("article", { name: "Answer" })).toContainText("↺ Asked before");
  await page.getByRole("button", { name: "Regenerate" }).click();
  await expect(page.getByRole("article", { name: "Answer" })).toContainText("Fresh.");
  expect(sent.fresh).toEqual(["", "true"]);
  expect(sent.bodies[1]).toEqual({ question: "How is a signature checked?" });
});

test("high contrast is switched on in Settings and kept on every page", async ({ page }) => {
  await mock(page, []);
  await page.goto("/chat");
  await page.getByRole("button", { name: "⚙ Settings" }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });
  await settings.getByRole("tab", { name: "Transparency" }).click();
  await settings.getByRole("switch", { name: /High contrast/ }).check();
  await expect(page.locator("html")).toHaveAttribute("data-contrast", "high");

  await page.goto("/health");
  await expect(page.locator("html")).toHaveAttribute("data-contrast", "high");
});

test("the theme is dark by default, switched in the top bar and kept on every page", async ({
  page,
}) => {
  await mock(page, []);
  await page.goto("/chat");
  const html = page.locator("html");
  await expect(html).not.toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Switch to the light theme" }).click();
  await expect(html).toHaveAttribute("data-theme", "light");

  await page.goto("/health");
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Switch to the dark theme" }).click();
  await expect(html).not.toHaveAttribute("data-theme", "light");
});

test("the chat list folds away for one centred column, and stays so", async ({ page }) => {
  await mock(page, []);
  await page.goto("/chat");
  const chats = page.getByRole("complementary", { name: "Saved chats" });
  await expect(chats).toBeVisible();
  await page.getByRole("button", { name: "Hide the chat list" }).click();
  await expect(chats).toBeHidden();
  await page.reload();
  await expect(chats).toBeHidden();
  await page.getByRole("button", { name: "Show the chat list" }).click();
  await expect(chats).toBeVisible();
});

test("every answer says where it stands, and an absent one asks what is missing", async ({ page }) => {
  const sent = await mock(page, [
    reply("It splits the value. Missing: the timestamp check.", { epistemic: "partial" }),
    reply("I don't have that in the knowledge base.", { epistemic: "absent" }),
    reply("Canberra.", { epistemic: "general" }),
  ]);
  await page.route("**/api/ask", async (route) => {
    const body = route.request().postDataJSON() as AskRequest;
    if (body.task !== "gaps") return route.fallback();
    sent.bodies.push(body);
    return route.fulfill({
      json: reply("2. Missing: verify_token_v2.", {
        gaps: { report: "2. Missing: verify_token_v2.", suggestion_url: null, found_by: "x" },
      }),
    });
  });
  await page.goto("/chat");
  await ask(page, "How is it unsigned?");
  const answers = page.getByRole("article", { name: "Answer" });
  await expect(answers.nth(0).getByRole("note", { name: /Epistemic state: Partial/ })).toBeVisible();

  await ask(page, "What does verify_token_v2 do?");
  await expect(answers.nth(1).getByRole("note", { name: /Epistemic state: Not in your sources/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "What's missing" })).toContainText("verify_token_v2");

  await ask(page, "What is the capital of Australia?");
  await expect(answers.nth(2).getByRole("note", { name: /Epistemic state: General knowledge/ })).toBeVisible();
  expect(sent.bodies.filter((b) => b.task === "gaps")).toHaveLength(1);
});
