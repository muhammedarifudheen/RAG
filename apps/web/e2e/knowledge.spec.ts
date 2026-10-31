import type { AskRequest, AskResponse, HealthReport, KnowledgeHealth } from "@atlas/shared";
import { expect, test } from "@playwright/test";

import { HEALTH, HEALTH_RANKING } from "./fixtures";

// The knowledge base improving itself: each question carries its chat, and the
// knowledge-health note shows at the end of a chat, on request, and on the Health page.

const NOTE: KnowledgeHealth = {
  scope: "chat",
  answers: 3,
  gaps: [{ question: "How do Flask sessions work?", times: 3 }],
  sources: [{ action: "add", source: "https://github.com/pallets/flask", why: "Suggested for 3 gap(s)" }],
  well_answered: { question: "What does format_name return?", score: 0.41 },
};

function reply(answer: string): AskResponse {
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
  };
}

test("a chat's questions carry its id, and starting a new chat shows the last one's health", async ({
  page,
}) => {
  const chats: string[] = [];
  const asked: string[] = [];
  await page.route("**/api/ask", (route) => {
    chats.push(route.request().headers()["x-atlas-chat"] ?? "");
    return route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body:
        `event: route\ndata: ${JSON.stringify({ route: "general", mode: "auto", providers: ["groq"] })}\n\n` +
        `event: done\ndata: ${JSON.stringify(reply("Sessions are signed cookies."))}\n\n`,
    });
  });
  await page.route("**/api/health*", (route) => {
    const chat = new URL(route.request().url()).searchParams.get("chat");
    if (chat) asked.push(chat); // not the wake-up ping, /healthz
    const report: HealthReport = { ...HEALTH, knowledge_health: NOTE };
    return route.fulfill({ json: report });
  });
  await page.goto("/chat");
  await page.getByLabel("Question", { exact: true }).fill("How do Flask sessions work?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByRole("article", { name: "Answer" })).toContainText("signed cookies");
  expect(chats[0]).toMatch(/\w{6,}/);

  await page.getByRole("button", { name: "Knowledge health" }).click();
  const note = page.getByRole("region", { name: "Knowledge health" });
  await expect(note).toContainText("Knowledge health of this chat");
  await note.getByRole("button", { name: "Close the knowledge health note" }).click();
  await expect(note).toHaveCount(0);

  await page.getByRole("complementary", { name: "Saved chats" }).getByRole("button", { name: "+ New chat" }).click();
  await expect(note).toContainText("Knowledge health of your last chat");
  await expect(note.getByRole("list", { name: "Recurring gaps" })).toContainText("How do Flask sessions work? (3×)");
  await expect(note.getByRole("link", { name: "https://github.com/pallets/flask" })).toBeVisible();
  await expect(note).toContainText("What does format_name return?");
  expect(asked).toEqual([chats[0], chats[0]]);
});

test("the Health page shows the knowledge health over everything logged", async ({ page }) => {
  await page.route("**/api/health*", (route) => {
    const ranking = new URL(route.request().url()).searchParams.has("max_function_loc");
    return route.fulfill({ json: ranking ? HEALTH_RANKING : { ...HEALTH, knowledge_health: { ...NOTE, scope: "all" } } });
  });
  await page.goto("/health");
  const note = page.getByRole("region", { name: "Knowledge health" });
  await expect(note).toContainText("From 3 logged answers.");
  await expect(note.getByRole("list", { name: "Sources to add or refresh" })).toContainText("Add");
});

void (null as unknown as AskRequest);
