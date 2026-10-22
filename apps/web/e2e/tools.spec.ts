import type { AskRequest, AskResponse } from "@atlas/shared";
import { expect, test, type Page } from "@playwright/test";

// The chat page's tools: attachments, pictures, settings, editing, sharing, export.

function reply(answer: string, extra: Partial<AskResponse> = {}): AskResponse {
  return {
    question: "q",
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

/** Answers each question with the next reply as a stream, recording the bodies sent. */
async function mockAssistant(page: Page, replies: AskResponse[]): Promise<AskRequest[]> {
  const sent: AskRequest[] = [];
  await page.route("**/api/ask", (route) => {
    sent.push(route.request().postDataJSON() as AskRequest);
    const next = replies.shift() ?? reply("(no more replies)");
    return route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body: [
        `event: route\ndata: ${JSON.stringify({ route: next.route, mode: "auto", providers: [] })}\n\n`,
        `event: delta\ndata: ${JSON.stringify({ text: next.answer })}\n\n`,
        `event: done\ndata: ${JSON.stringify(next)}\n\n`,
      ].join(""),
    });
  });
  return sent;
}

async function ask(page: Page, question: string) {
  await page.getByLabel("Question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();
}

const answers = (page: Page) => page.getByRole("article", { name: "Answer", exact: true });

// A 1×1 PNG.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

test("a document is read by the API and sent with the question", async ({ page }) => {
  await page.route("**/api/attachments", (route) =>
    route.fulfill({ json: { name: "notes.pdf", kind: "text", text: "Launch is on Friday.", truncated: false } }),
  );
  const sent = await mockAssistant(page, [reply("The launch is on Friday.")]);
  await page.goto("/chat");

  await page.getByLabel("Files to attach").setInputFiles({
    name: "notes.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 stand-in"),
  });
  const attached = page.getByRole("list", { name: "Attached files" });
  await expect(attached).toContainText("notes.pdf");
  await ask(page, "When is the launch?");

  await expect(answers(page)).toContainText("The launch is on Friday.");
  expect(sent[0].attachments).toEqual([{ name: "notes.pdf", kind: "text", text: "Launch is on Friday." }]);
  // The file is listed with the question, and the box is empty again.
  await expect(page.getByRole("log").getByText("notes.pdf")).toBeVisible();
  await expect(attached).toHaveCount(0);

  // A follow-up still carries the file, so it can be asked about again.
  await ask(page, "And what time?");
  await expect(answers(page)).toHaveCount(2);
  expect(sent[1].attachments?.[0].name).toBe("notes.pdf");
  expect(sent[1].history?.[0].content).toContain("[Attached: notes.pdf]");
});

test("an image is sent as base64 and shown with the question", async ({ page }) => {
  const sent = await mockAssistant(page, [reply("A single pixel.", { route: "vision" })]);
  await page.goto("/chat");
  await page.getByLabel("Files to attach").setInputFiles({
    name: "dot.png",
    mimeType: "image/png",
    buffer: PNG,
  });
  await expect(page.getByRole("list", { name: "Attached files" })).toContainText("dot.png");
  await ask(page, "What is in this image?");

  await expect(answers(page)).toContainText("A single pixel.");
  const [image] = sent[0].attachments ?? [];
  expect(image).toMatchObject({ name: "dot.png", kind: "image", mime: "image/png" });
  expect(image.data).toBe(PNG.toString("base64"));
  await expect(page.getByRole("log").getByRole("img", { name: "dot.png" })).toBeVisible();
});

test("the Draw switch asks for a picture, which is shown with links to it", async ({ page }) => {
  await page.route("https://draw.example/**", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: PNG }),
  );
  const sent = await mockAssistant(page, [
    reply("Here's your picture, drawn from this description:\n\n> A red fox in snow", {
      route: "image",
      provider: "Groq",
      model: "flux",
      images: [{ url: "https://draw.example/fox.png", prompt: "A red fox in snow" }],
      suggestions: ["Draw another version"],
    }),
  ]);
  await page.goto("/chat");

  const draw = page.getByRole("button", { name: "Draw a picture" });
  await draw.click();
  await expect(draw).toHaveAttribute("aria-pressed", "true");
  await ask(page, "a red fox in snow");

  const picture = answers(page).getByRole("img", { name: "A red fox in snow" });
  await expect(picture).toHaveAttribute("src", "https://draw.example/fox.png");
  await expect(answers(page).getByRole("link", { name: "Open full size" })).toHaveAttribute(
    "href",
    "https://draw.example/fox.png",
  );
  expect(sent[0].task).toBe("image");
  // The switch turns itself off after one picture.
  await expect(draw).toHaveAttribute("aria-pressed", "false");
});

test("settings are kept and sent with every question", async ({ page }) => {
  const sent = await mockAssistant(page, [reply("Bref."), reply("Encore.")]);
  await page.goto("/chat");

  await page.getByRole("button", { name: "⚙ Settings" }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });
  await settings.getByRole("radio", { name: /Concise/ }).click();
  await settings.getByLabel("Let each model use its own default").uncheck();
  await settings.getByLabel("Temperature").fill("0.3");
  await settings.getByLabel("Custom instructions").fill("Answer in French.");
  await settings.getByRole("button", { name: "Close settings" }).click();
  await expect(settings).toBeHidden();

  await ask(page, "What is HMAC?");
  await expect(answers(page)).toHaveCount(1);
  expect(sent[0]).toMatchObject({
    style: "concise",
    temperature: 0.3,
    instructions: "Answer in French.",
  });

  // Still set after a reload.
  await page.reload();
  await ask(page, "Again?");
  await expect(answers(page)).toHaveCount(1);
  expect(sent[1]).toMatchObject({ style: "concise", instructions: "Answer in French." });
});

test("an answer can be copied and regenerated, and a question edited and sent again", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const sent = await mockAssistant(page, [
    reply("First answer."),
    reply("Second answer."),
    reply("Answer to the edit."),
  ]);
  await page.goto("/chat");
  await ask(page, "Tell me a fact");
  await expect(answers(page)).toContainText("First answer.");

  await page.getByRole("button", { name: "Copy answer" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("First answer.");

  // Regenerate replaces the last answer, asking the same question with the same history.
  await page.getByRole("button", { name: "Regenerate" }).click();
  await expect(answers(page)).toHaveCount(1);
  await expect(answers(page)).toContainText("Second answer.");
  expect(sent[1]).toEqual({ question: "Tell me a fact" });

  // Editing a question drops what came after it and asks the new wording.
  await page.getByRole("log").getByText("Tell me a fact").hover();
  await page.getByRole("button", { name: "Edit message" }).click();
  await page.getByLabel("Edit your message").fill("Tell me a fact about owls");
  await page.getByRole("button", { name: "Send edit" }).click();
  await expect(answers(page)).toHaveCount(1);
  await expect(answers(page)).toContainText("Answer to the edit.");
  expect(sent[2]).toEqual({ question: "Tell me a fact about owls" });
});

test("code blocks are labelled and copyable, and maths is typeset", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await mockAssistant(page, [
    reply("Use this:\n\n```python\nprint('hi')\n```\n\nand $E = mc^2$, or\n\n$$a^2 + b^2 = c^2$$"),
  ]);
  await page.goto("/chat");
  await ask(page, "Show me code and maths");

  const answer = answers(page);
  await expect(answer.getByText("python", { exact: true })).toBeVisible();
  await answer.getByRole("button", { name: "Copy code" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("print('hi')");
  await expect(answer.getByRole("button", { name: "Copied" })).toBeVisible();
  await expect(answer.locator(".katex")).toHaveCount(2);
  await expect(answer.locator(".katex-display")).toHaveCount(1);
});

test("chats can be renamed, pinned and searched", async ({ page }) => {
  await mockAssistant(page, [reply("TCP is reliable."), reply("UDP is fast.")]);
  await page.goto("/chat");
  const saved = page.getByRole("complementary", { name: "Saved chats" });

  await ask(page, "What is TCP?");
  await expect(answers(page)).toHaveCount(1);
  await saved.getByRole("button", { name: "+ New chat" }).click();
  await ask(page, "What is UDP?");
  await expect(answers(page)).toHaveCount(1);

  // Newest first, until the older one is pinned.
  await expect(saved.getByRole("listitem").first()).toContainText("What is UDP?");
  await saved.getByRole("button", { name: "Pin chat What is TCP?" }).click();
  await expect(saved.getByRole("listitem").first()).toContainText("What is TCP?");

  await saved.getByRole("button", { name: "Rename chat What is TCP?" }).click();
  await saved.getByLabel("New chat name").fill("Networking basics");
  await saved.getByLabel("New chat name").press("Enter");
  await expect(saved.getByRole("button", { name: "Networking basics", exact: true })).toBeVisible();

  // Search looks in titles and in what was said.
  await saved.getByLabel("Search chats").fill("fast");
  await expect(saved.getByRole("listitem")).toHaveCount(1);
  await expect(saved.getByRole("listitem")).toContainText("What is UDP?");

  await page.reload();
  await expect(saved.getByRole("button", { name: "Networking basics", exact: true })).toBeVisible();
});

test("a chat is shared by link and can be continued from the shared page", async ({ page }) => {
  await mockAssistant(page, [reply("A keyed hash.", { suggestions: [] })]);
  let shared: { title: string; messages: unknown[] } | null = null;
  await page.route("**/api/shares", (route) => {
    shared = route.request().postDataJSON();
    return route.fulfill({
      status: 201,
      json: { id: "abc123XYZ", ...shared, created_at: "2026-10-22T10:00:00Z" },
    });
  });
  await page.route("**/api/shares/abc123XYZ", (route) =>
    route.fulfill({ json: { id: "abc123XYZ", ...shared, created_at: "2026-10-22T10:00:00Z" } }),
  );
  await page.goto("/chat");
  await ask(page, "What is HMAC?");
  await expect(answers(page)).toHaveCount(1);

  await page.getByRole("button", { name: "Share" }).click();
  const link = page.getByRole("dialog", { name: "Share chat" }).getByLabel("Link to the shared chat");
  await expect(link).toHaveValue(/\/share\/\?id=abc123XYZ$/);
  expect(shared!.title).toBe("What is HMAC?");

  await page.goto("/share?id=abc123XYZ");
  await expect(page.getByRole("heading", { name: "What is HMAC?" })).toBeVisible();
  await expect(answers(page)).toContainText("A keyed hash.");
  await page.getByRole("button", { name: "Continue this chat" }).click();

  await expect(page).toHaveURL(/\/chat\?c=/);
  await expect(answers(page)).toContainText("A keyed hash.");
  await expect(page.getByRole("complementary", { name: "Saved chats" }).getByRole("listitem")).toHaveCount(2);
});

test("a chat is exported as Markdown", async ({ page }) => {
  await mockAssistant(page, [reply("**Paris.**")]);
  await page.goto("/chat");
  await ask(page, "Capital of France?");
  await expect(answers(page)).toHaveCount(1);

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("capital-of-france.md");
  const text = await (await file.createReadStream()).toArray();
  expect(Buffer.concat(text).toString()).toBe(
    "# Capital of France?\n\n## You\n\nCapital of France?\n\n## Atlas\n\n**Paris.**\n",
  );
});

test("keyboard: Enter sends, Shift+Enter breaks the line, Ctrl+/ lists the shortcuts", async ({
  page,
}) => {
  const sent = await mockAssistant(page, [reply("Two lines received.")]);
  await page.goto("/chat");
  const box = page.getByLabel("Question");
  await box.click();
  await box.pressSequentially("line one");
  await box.press("Shift+Enter");
  await box.pressSequentially("line two");
  await box.press("Enter");

  await expect(answers(page)).toContainText("Two lines received.");
  expect(sent[0].question).toBe("line one\nline two");

  await page.keyboard.press("Control+/");
  const shortcuts = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(shortcuts).toContainText("Search chats");
  await page.keyboard.press("Escape");
  await expect(shortcuts).toBeHidden();
});

test("a starter on the empty page asks its question", async ({ page }) => {
  const sent = await mockAssistant(page, [reply("Sorted.")]);
  await page.goto("/chat");
  await page.getByRole("button", { name: /removes duplicates from a list/ }).click();
  await expect(answers(page)).toContainText("Sorted.");
  expect(sent[0].question).toMatch(/^Write a Python function/);
});
