import type { AskRequest, AskResponse } from "@atlas/shared";
import { expect, test, type Page, type Route } from "@playwright/test";

import { alerts } from "./fixtures";

// The assistant answers anything and streams its answer as server-sent events.

function reply(question: string, answer: string, extra: Partial<AskResponse> = {}): AskResponse {
  return {
    question,
    answer,
    citations: [],
    chunks: [],
    model: "gemini-3.6-flash",
    complete: true,
    provider: "Gemini",
    route: "general",
    suggestions: [],
    web_sources: [],
    ...extra,
  };
}

function stream(events: [string, unknown][]): string {
  return events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

function fulfillStream(route: Route, events: [string, unknown][]) {
  return route.fulfill({
    status: 200,
    headers: { "content-type": "text/event-stream" },
    body: stream(events),
  });
}

interface Sent {
  body: AskRequest;
  mode: string | undefined;
  accept: string | undefined;
}

/** Answers each question with the next of `replies`, recording what was sent. */
async function mockAssistant(page: Page, replies: AskResponse[]): Promise<Sent[]> {
  const sent: Sent[] = [];
  await page.route("**/api/ask", (route) => {
    const request = route.request();
    sent.push({
      body: request.postDataJSON() as AskRequest,
      mode: request.headers()["x-atlas-mode"],
      accept: request.headers()["accept"],
    });
    const next = replies.shift();
    if (!next) return route.abort();
    const half = Math.ceil(next.answer.length / 2);
    return fulfillStream(route, [
      ["route", { route: next.route, mode: "auto", providers: ["gemini"] }],
      ["delta", { text: next.answer.slice(0, half) }],
      ["delta", { text: next.answer.slice(half) }],
      ["done", next],
    ]);
  });
  return sent;
}

async function ask(page: Page, question: string) {
  await page.getByLabel("Question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();
}

test("answers anything and lists the web pages it used", async ({ page }) => {
  const sent = await mockAssistant(page, [
    reply("Who won the 2022 World Cup?", "**Argentina** won it, beating France on penalties.", {
      route: "current",
      web_sources: [{ title: "2022 FIFA World Cup", url: "https://example.com/wc2022" }],
      suggestions: ["Who was the top scorer?", "Where was it held?", "Who won in 2018?"],
    }),
  ]);
  await page.goto("/chat");
  await ask(page, "Who won the 2022 World Cup?");

  const answer = page.getByRole("article", { name: "Answer" });
  await expect(answer.locator("strong")).toHaveText("Argentina");
  // Which AI service answered is not shown.
  await expect(answer).not.toContainText("Gemini");
  await expect(answer.getByRole("link", { name: "2022 FIFA World Cup" })).toHaveAttribute(
    "href",
    "https://example.com/wc2022",
  );
  // No sources were used, so there is no excerpt list.
  await expect(answer).not.toContainText("excerpts were given");

  const offered = page.getByRole("group", { name: "Suggested questions" }).getByRole("button");
  await expect(offered).toHaveText(["Who was the top scorer?", "Where was it held?", "Who won in 2018?"]);

  // The first question goes on its own, asking for a stream, in the default mode.
  expect(sent[0].body).toEqual({ question: "Who won the 2022 World Cup?" });
  expect(sent[0].accept).toContain("text/event-stream");
  expect(sent[0].mode).toBe("auto");
});

test("follow-ups carry the conversation, and a suggestion can be asked with one click", async ({ page }) => {
  const sent = await mockAssistant(page, [
    reply("What is HMAC?", "A keyed hash for message authentication.", {
      suggestions: ["How is it different from a plain hash?"],
    }),
    reply("How is it different from a plain hash?", "It needs a secret key."),
    reply("And in Python?", "Use the hmac module."),
  ]);
  await page.goto("/chat");

  await ask(page, "What is HMAC?");
  await page.getByRole("button", { name: "How is it different from a plain hash?" }).click();
  await expect(page.getByRole("article", { name: "Answer" })).toHaveCount(2);
  await ask(page, "And in Python?");
  await expect(page.getByRole("article", { name: "Answer" })).toHaveCount(3);

  expect(sent[1].body).toEqual({
    question: "How is it different from a plain hash?",
    history: [
      { role: "user", content: "What is HMAC?" },
      { role: "assistant", content: "A keyed hash for message authentication." },
    ],
  });
  expect(sent[2].body.history).toHaveLength(4);
  // Suggestions are offered under the latest answer only.
  await expect(page.getByRole("group", { name: "Suggested questions" })).toHaveCount(0);
});

test("the answer appears while it is written, and a switch of model starts it over", async ({
  page,
}) => {
  let release: () => void = () => {};
  const released = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/ask", async (route) => {
    await released;
    await fulfillStream(route, [
      ["route", { route: "general", mode: "auto", providers: ["gemini", "groq"] }],
      ["delta", { text: "A half-written answer from the first model that" }],
      ["reset", { provider: "Gemini" }],
      ["delta", { text: "The second model's whole answer." }],
      ["done", reply("q", "The second model's whole answer.", { provider: "Groq", model: "llama" })],
    ]);
  });
  await page.goto("/chat");
  await ask(page, "q");

  await expect(page.getByRole("status")).toContainText("Searching the knowledge base");
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
  release();

  const answer = page.getByRole("article", { name: "Answer" });
  await expect(answer).toContainText("The second model's whole answer.");
  await expect(answer).not.toContainText("half-written");
  await expect(page.getByRole("button", { name: "Ask" })).toBeVisible();
});

test("an error from the assistant is shown and another question can be asked", async ({ page }) => {
  await page.route("**/api/ask", (route) =>
    fulfillStream(route, [
      ["route", { route: "general", mode: "auto", providers: ["gemini"] }],
      ["error", { status: 503, detail: "Every AI service failed; the last said: quota" }],
    ]),
  );
  await page.goto("/chat");
  await ask(page, "Anything?");

  await expect(alerts(page)).toHaveText("Every AI service failed; the last said: quota");
  await expect(page.getByLabel("Question")).toBeEditable();
});

test("the mode switch is remembered and sent with each question", async ({ page }) => {
  const sent = await mockAssistant(page, [reply("q1", "a1"), reply("q2", "a2")]);
  await page.goto("/chat");

  const models = page.getByRole("radiogroup", { name: "Models" });
  await expect(models.getByRole("radio", { name: "Auto" })).toHaveAttribute("aria-checked", "true");
  await models.getByRole("radio", { name: "Best model" }).click();
  await ask(page, "q1");
  await expect(page.getByRole("article", { name: "Answer" })).toHaveCount(1);
  expect(sent[0].mode).toBe("best");

  await page.reload();
  await expect(models.getByRole("radio", { name: "Best model" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
});

test("chats are saved in the browser, reopened, started afresh and deleted", async ({ page }) => {
  await mockAssistant(page, [reply("What is TCP?", "A reliable transport."), reply("Hi", "Hello!")]);
  await page.goto("/chat");
  const saved = page.getByRole("complementary", { name: "Saved chats" });

  await ask(page, "What is TCP?");
  await expect(saved.getByRole("button", { name: "What is TCP?", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await saved.getByRole("button", { name: "+ New chat" }).click();
  await expect(page.getByRole("article", { name: "Answer" })).toHaveCount(0);
  await ask(page, "Hi");
  await expect(saved.getByRole("button", { name: "Hi", exact: true })).toBeVisible();

  // After a reload both are listed, newest first, and the first opens again.
  await page.reload();
  await expect(saved.getByRole("listitem")).toHaveCount(2);
  await expect(saved.getByRole("listitem").first()).toContainText("Hi");
  await saved.getByRole("button", { name: "What is TCP?", exact: true }).click();
  await expect(page.getByRole("article", { name: "Answer" })).toContainText("A reliable transport.");

  await saved.getByRole("button", { name: "Delete chat What is TCP?" }).click();
  await expect(saved.getByRole("listitem")).toHaveCount(1);
  await expect(page.getByRole("article", { name: "Answer" })).toHaveCount(0);
});

test("an answer can be stopped", async ({ page }) => {
  await page.route("**/api/ask", () => {
    // Never answers.
  });
  await page.goto("/chat");
  await ask(page, "A long question");
  await page.getByRole("button", { name: "Stop" }).click();

  await expect(alerts(page)).toHaveText("You stopped this answer.");
  await expect(page.getByRole("button", { name: "Ask" })).toBeVisible();
});

test("an answer searched on the web first still streams and links its sources", async ({ page }) => {
  const news = { title: "Python 3.15 released", url: "https://news.example/python-3-15" };
  await page.route("**/api/ask", (route) =>
    fulfillStream(route, [
      ["route", { route: "current", mode: "auto", providers: ["gemini"] }],
      ["searching", {}],
      ["web", { sources: [news] }],
      ["delta", { text: "Python **3.15** came out on 10 October 2026." }],
      [
        "done",
        reply("latest python?", "Python **3.15** came out on 10 October 2026.", {
          route: "current",
          web_sources: [news],
        }),
      ],
    ]),
  );
  await page.goto("/chat");
  await ask(page, "latest python?");

  const answer = page.getByRole("article", { name: "Answer" });
  await expect(answer).toContainText("Python 3.15 came out on 10 October 2026.");
  await expect(answer.getByRole("link", { name: "Python 3.15 released" })).toHaveAttribute(
    "href",
    news.url,
  );
});
