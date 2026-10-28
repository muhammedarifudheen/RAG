import type { AskRequest, AskResponse } from "@atlas/shared";
import { expect, test, type Page } from "@playwright/test";

// The AI, retrieval, generation and transparency controls in Settings, and what they send.

function reply(answer: string, extra: Partial<AskResponse> = {}): AskResponse {
  return {
    question: "q",
    answer,
    citations: [],
    chunks: [],
    model: "m",
    complete: true,
    provider: "Atlas council",
    route: "general",
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
        `event: route\ndata: ${JSON.stringify({ route: "general", mode: "auto", providers: ["gemini", "groq", "nvidia"] })}\n\n` +
        `event: done\ndata: ${JSON.stringify(next)}\n\n`,
    });
  });
  return sent;
}

async function ask(page: Page, question: string) {
  await page.getByLabel("Question", { exact: true }).fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
}

test("nothing extra is sent until a control is changed", async ({ page }) => {
  const sent = await mock(page, [reply("Hi.")]);
  await page.goto("/chat");
  await ask(page, "hello");
  await expect(page.getByRole("article", { name: "Answer" })).toBeVisible();
  expect(sent[0]).toEqual({ question: "hello" });
});

test("models, retrieval, generation and transparency choices go with every question", async ({
  page,
}) => {
  const drafts = [
    { agent: "Gemini · flash", seconds: 2.1, answer: "Gemini's **draft**." },
    { agent: "Groq · gpt-oss", seconds: 0.8, answer: "Groq's draft." },
  ];
  const sent = await mock(page, [reply("First."), reply("Merged.", { drafts })]);
  await page.goto("/chat");
  // A first answer tells the page which services this server has.
  await ask(page, "warm up");
  await expect(page.getByRole("article", { name: "Answer" })).toBeVisible();

  await page.getByRole("button", { name: "⚙ Settings" }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });

  await settings.getByLabel("Persona").selectOption({ label: "Senior engineer" });
  await settings.getByLabel("Output format").selectOption({ label: "JSON" });
  await settings.getByLabel("Maximum length").selectOption({ label: "Medium (1,500)" });

  await settings.getByRole("tab", { name: "Models" }).click();
  const services = settings.getByRole("list", { name: "AI services" });
  await expect(services.getByRole("listitem").filter({ hasText: "Groq" }).getByLabel("available")).toBeVisible();
  await services.getByLabel("Groq").check();
  await services.getByLabel("NVIDIA").check();
  await settings.getByLabel("Agents per question").fill("3");
  await settings.getByLabel("Merged by").selectOption({ label: "Groq" });

  await settings.getByRole("tab", { name: "Retrieval" }).click();
  await settings.getByLabel("Excerpts per question (top-k)").fill("12");
  await settings.getByLabel("Relevance threshold").fill("0.5");
  await settings.getByRole("switch", { name: /Search the web/ }).uncheck();

  await settings.getByRole("tab", { name: "Transparency" }).click();
  await settings.getByRole("switch", { name: /Show every agent's own draft/ }).check();
  await settings.getByRole("button", { name: "Close settings" }).click();

  await ask(page, "Compare them");
  await expect(page.getByRole("article", { name: "Answer" }).nth(1)).toContainText("Merged.");
  expect(sent[1]).toMatchObject({
    question: "Compare them",
    services: ["groq", "nvidia"],
    council_size: 3,
    merger: "groq",
    top_k: 12,
    min_score: 0.5,
    web_search: false,
    max_tokens: 1500,
    format: "json",
    include_drafts: true,
  });
  expect(sent[1].instructions).toContain("senior software engineer");

  const answer = page.getByRole("article", { name: "Answer" }).nth(1);
  await answer.getByText("2 agent drafts, before the merge").click();
  await expect(answer.getByRole("region", { name: "Draft by Gemini · flash" })).toContainText(
    "Gemini's draft.",
  );
  await expect(answer.getByRole("region", { name: "Draft by Groq · gpt-oss" })).toContainText("0.8s");
});

test("the strict switch asks for cited answers from the sources only, and is remembered", async ({
  page,
}) => {
  const sent = await mock(page, [
    reply("I don't have that in the knowledge base.", { provider: "Atlas", route: "sources" }),
    reply("Again."),
  ]);
  await page.goto("/chat");
  const strict = page.getByRole("button", { name: "Strict sources only" });
  await expect(strict).toHaveAttribute("aria-pressed", "false");
  await strict.click();
  await expect(strict).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Question", { exact: true })).toHaveAttribute(
    "placeholder",
    /strict/,
  );
  await ask(page, "Who won the cup?");
  await expect(page.getByRole("article", { name: "Answer" })).toContainText(
    "I don't have that in the knowledge base.",
  );
  expect(sent[0]).toEqual({ question: "Who won the cup?", strict: true });

  // Kept after a reload, and shown in Settings → Retrieval.
  await page.reload();
  await expect(page.getByRole("button", { name: "Strict sources only" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "⚙ Settings" }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });
  await settings.getByRole("tab", { name: "Retrieval" }).click();
  await expect(settings.getByRole("switch", { name: /Strict sources only/ })).toBeChecked();
});
