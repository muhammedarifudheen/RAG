import type { AskRequest, AskResponse, ResearchStep } from "@atlas/shared";
import { expect, test, type Page } from "@playwright/test";

// Deep research: the agent's steps as they happen and under the answer, and its switches.

const STEPS: ResearchStep[] = [
  { step: 1, tool: "search", input: "unsign verify signature", result: "5 results" },
  { step: 2, tool: "read", input: "src/signer.py:227-260", result: "read" },
  { step: 3, tool: "note", input: "verify_signature compares in constant time", result: "saved" },
];

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

async function mock(page: Page, answers: AskResponse[]): Promise<AskRequest[]> {
  const sent: AskRequest[] = [];
  await page.route("**/api/ask", (route) => {
    const body = route.request().postDataJSON() as AskRequest;
    sent.push(body);
    const next = answers.shift() ?? reply("…");
    const steps = (next.research_steps ?? [])
      .map((step) => `event: researching\ndata: ${JSON.stringify(step)}\n\n`)
      .join("");
    return route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body:
        `event: route\ndata: ${JSON.stringify({ route: "sources", mode: "auto", providers: ["groq"] })}\n\n` +
        steps +
        `event: done\ndata: ${JSON.stringify(next)}\n\n`,
    });
  });
  return sent;
}

async function ask(page: Page, question: string) {
  await page.getByLabel("Question", { exact: true }).fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
}

test("the research switch asks for deep research, and its steps are listed under the answer", async ({
  page,
}) => {
  const sent = await mock(page, [
    reply("It decodes, then compares.", { research_steps: STEPS }),
    reply("Plain."),
  ]);
  await page.goto("/chat");
  const research = page.getByRole("button", { name: "Deep research" });
  await expect(research).toHaveAttribute("aria-pressed", "false");
  await research.click();
  await expect(research).toHaveAttribute("aria-pressed", "true");
  await ask(page, "Trace how unsign checks a signature");

  const answer = page.getByRole("article", { name: "Answer" });
  await answer.getByText("Researched in 3 steps").click();
  const steps = answer.getByRole("list", { name: "Research steps" }).getByRole("listitem");
  await expect(steps).toHaveCount(3);
  await expect(steps.nth(1)).toContainText("src/signer.py:227-260");
  await expect(steps.nth(2)).toContainText("saved");

  // Off again, and automatic research turned off in Settings: never.
  await research.click();
  await page.getByRole("button", { name: "⚙ Settings" }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });
  await settings.getByRole("tab", { name: "Retrieval" }).click();
  await settings.getByRole("switch", { name: /Deep research for complex questions/ }).uncheck();
  await settings.getByRole("button", { name: "Close settings" }).click();
  await ask(page, "And now?");
  await expect(page.getByRole("article", { name: "Answer" }).nth(1)).toContainText("Plain.");

  expect(sent[0].research).toBe(true);
  expect(sent[1].research).toBe(false);
});
