import type { AskRequest } from "@atlas/shared";
import { expect, test, type Page } from "@playwright/test";

import { ANSWER, MODELS_FILE, alerts, apiError, mockFiles } from "./fixtures";

async function askQuestion(page: Page, question: string): Promise<void> {
  await page.goto("/chat");
  await page.getByLabel("Question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();
}

test("renders the answer as Markdown with clickable citations", async ({ page }) => {
  let posted: AskRequest | null = null;
  await page.route("**/api/ask", (route) => {
    posted = route.request().postDataJSON() as AskRequest;
    return route.fulfill({ json: ANSWER });
  });

  await askQuestion(page, ANSWER.question);

  const log = page.getByRole("log", { name: "Conversation" });
  await expect(log.getByText(ANSWER.question)).toBeVisible();
  expect(posted).toEqual({ question: ANSWER.question });

  const answer = page.getByRole("article", { name: "Answer" });
  // Markdown is rendered, not shown as source.
  await expect(answer.locator("strong")).toHaveText("title-cased");
  await expect(answer.locator(".markdown li")).toHaveCount(2);
  await expect(answer).not.toContainText("**");

  // Each citation is a button labelled with its range.
  await expect(answer.getByRole("button", { name: "pkg/models.py:20-21" })).toBeVisible();
  await expect(answer.getByRole("button", { name: "pkg/models.py:21-21" })).toBeVisible();

  // A citation the API could not verify is marked as such.
  const unverified = answer.getByRole("button", { name: /pkg\/store\.py:1-9/ });
  await expect(unverified).toContainText("(unverified)");
  await expect(unverified).toHaveAttribute("data-verified", "false");
  await expect(answer.getByRole("button", { name: "pkg/models.py:20-21" })).toHaveAttribute(
    "data-verified",
    "true",
  );

  // A citation inside a code span stays literal text.
  await expect(answer.locator(".markdown code").last()).toHaveText("[pkg/models.py:1-2]");
  await expect(answer.getByRole("button", { name: "pkg/models.py:1-2" })).toHaveCount(0);

  await expect(answer).toContainText("1 code excerpts were given to claude-opus-5-5");
});

test("clicking a citation opens the code with the cited lines highlighted", async ({ page }) => {
  await page.route("**/api/ask", (route) => route.fulfill({ json: ANSWER }));
  await mockFiles(page, [MODELS_FILE]);

  await askQuestion(page, ANSWER.question);
  const answer = page.getByRole("article", { name: "Answer" });
  const panel = page.getByRole("complementary", { name: "Cited code" });
  await expect(panel).toHaveCount(0);

  await answer.getByRole("button", { name: "pkg/models.py:20-21" }).click();

  await expect(panel).toBeVisible();
  await expect(panel.getByRole("heading")).toHaveText("pkg/models.py:20-21");

  // The whole file is shown, one .line per source line, with exactly the cited ones marked.
  const cited = panel.locator(".code-view .line.cited");
  await expect(cited).toHaveCount(2);
  await expect(cited.first()).toHaveText("def format_name(name: str) -> str:");
  await expect(cited.first()).toHaveAttribute("data-line", "20");
  await expect(cited.last()).toHaveText("    return name.strip().title()");
  await expect(panel.locator('.code-view .line[data-line="4"]')).toHaveText("class Base:");
  await expect(cited.first()).toBeInViewport();

  // Shiki produced coloured tokens: `def` and the function name differ in colour.
  await expect(panel.locator("pre.shiki")).toBeVisible();
  const colours = await cited
    .first()
    .locator("span")
    .evaluateAll((spans) => [...new Set(spans.map((s) => getComputedStyle(s).color))]);
  expect(colours.length).toBeGreaterThan(1);

  // Another citation into the same file moves the highlight.
  await answer.getByRole("button", { name: "pkg/models.py:21-21" }).click();
  await expect(panel.getByRole("heading")).toHaveText("pkg/models.py:21-21");
  await expect(cited).toHaveCount(1);
  await expect(cited).toHaveAttribute("data-line", "21");

  await panel.getByRole("button", { name: "Close code panel" }).click();
  await expect(panel).toHaveCount(0);
});

test("a citation to a file that was not ingested says so", async ({ page }) => {
  await page.route("**/api/ask", (route) => route.fulfill({ json: ANSWER }));
  await mockFiles(page, [MODELS_FILE]);

  await askQuestion(page, ANSWER.question);
  await page.getByRole("button", { name: /pkg\/store\.py:1-9/ }).click();

  const panel = page.getByRole("complementary", { name: "Cited code" });
  await expect(panel.getByRole("alert")).toHaveText("No ingested file at 'pkg/store.py'.");
});

test("the excerpts given to the model can be opened too", async ({ page }) => {
  await page.route("**/api/ask", (route) => route.fulfill({ json: ANSWER }));
  await mockFiles(page, [MODELS_FILE]);

  await askQuestion(page, ANSWER.question);
  const answer = page.getByRole("article", { name: "Answer" });
  await answer.getByText("1 code excerpts were given to").click();
  await answer.getByRole("button", { name: /function format_name/ }).click();

  const panel = page.getByRole("complementary", { name: "Cited code" });
  await expect(panel.locator(".code-view .line.cited")).toHaveCount(2);
});

test("a citation naming several places in a file becomes one button per place", async ({ page }) => {
  await page.route("**/api/ask", (route) =>
    route.fulfill({
      json: {
        ...ANSWER,
        answer: "Names are formatted in one place [pkg/models.py:20-21, 4-9].",
        citations: [
          { ref: "[pkg/models.py:20-21]", file: "pkg/models.py", start_line: 20, end_line: 21, verified: true },
          { ref: "[pkg/models.py:4-9]", file: "pkg/models.py", start_line: 4, end_line: 9, verified: false },
        ],
      },
    }),
  );
  await mockFiles(page, [MODELS_FILE]);

  await askQuestion(page, ANSWER.question);
  const answer = page.getByRole("article", { name: "Answer" });

  await expect(answer.getByRole("button", { name: "pkg/models.py:20-21" })).toHaveAttribute(
    "data-verified",
    "true",
  );
  const second = answer.getByRole("button", { name: /pkg\/models\.py:4-9/ });
  await expect(second).toHaveAttribute("data-verified", "false");
  await expect(answer).not.toContainText("20-21, 4-9");

  await second.click();
  const panel = page.getByRole("complementary", { name: "Cited code" });
  await expect(panel.locator(".code-view .line.cited")).toHaveCount(6);
});

test("shows the reason when the question cannot be answered", async ({ page }) => {
  await page.route("**/api/ask", (route) =>
    apiError(route, 503, "Anthropic credentials are not configured; set ANTHROPIC_API_KEY."),
  );

  await askQuestion(page, "Anything?");

  await expect(alerts(page)).toHaveText(
    "Anthropic credentials are not configured; set ANTHROPIC_API_KEY.",
  );
  // The question stays in the log and another can be asked.
  await expect(page.getByRole("log").getByText("Anything?")).toBeVisible();
  await expect(page.getByLabel("Question")).toBeEditable();
});
