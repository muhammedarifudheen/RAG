import type { AskRequest, AskResponse, CodeChunk, FactCheck } from "@atlas/shared";
import { expect, test, type Page } from "@playwright/test";

// The self-challenge: an answer from the sources is challenged once shown, and revised if
// the objection holds; a strict answer's fact-check then checks the final answer.

const excerpt: CodeChunk = {
  symbol_id: 7,
  name: "Signer.verify_signature",
  kind: "method",
  signature: null,
  file: "src/signer.py",
  language: "python",
  start_line: 227,
  end_line: 240,
  score: 0.7,
  snippet: "return hmac.compare_digest(a, b)",
  snippet_end_line: 240,
  truncated: false,
  citation: "[src/signer.py:227-240]",
};

const cite = [{ ref: "[src/signer.py:227-240]", file: "src/signer.py", start_line: 227, end_line: 240, verified: true }];

function reply(answer: string, extra: Partial<AskResponse> = {}): AskResponse {
  return {
    question: "How are signatures compared?",
    answer,
    citations: cite,
    chunks: [excerpt],
    model: "m",
    complete: true,
    provider: "Atlas council",
    route: "sources",
    suggestions: [],
    web_sources: [],
    ...extra,
  };
}

const ORIGINAL = "They are compared with == [src/signer.py:227-240].";
const REVISED = "They are compared in constant time with hmac.compare_digest [src/signer.py:227-240].";

async function mock(page: Page): Promise<AskRequest[]> {
  const sent: AskRequest[] = [];
  await page.route("**/api/ask", (route) => {
    const body = route.request().postDataJSON() as AskRequest;
    sent.push(body);
    if (body.task === "challenge") {
      return route.fulfill({
        json: reply(REVISED, {
          challenge: {
            objection: "The excerpt uses hmac.compare_digest, not ==.",
            valid: true,
            reason: "",
            original_answer: ORIGINAL,
            challenged_by: "NVIDIA · nemotron",
          },
        }),
      });
    }
    if (body.task === "check") {
      const check: FactCheck = { faithful: true, unsupported: [], citation_errors: [], verdict: "Supported.", checked_by: "x" };
      return route.fulfill({ json: reply(body.answer ?? "", { fact_check: check }) });
    }
    const first = reply(ORIGINAL, { epistemic: "known", challenge_pending: true, fact_check_pending: true });
    return route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body:
        `event: route\ndata: ${JSON.stringify({ route: "sources", mode: "auto", providers: ["groq"] })}\n\n` +
        `event: done\ndata: ${JSON.stringify(first)}\n\n`,
    });
  });
  return sent;
}

test("an answer is challenged once shown, revised when the objection holds, then fact-checked", async ({
  page,
}) => {
  const sent = await mock(page);
  await page.goto("/chat");
  await page.getByLabel("Question", { exact: true }).fill("How are signatures compared?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  const answer = page.getByRole("article", { name: "Answer" });
  await expect(answer).toContainText("hmac.compare_digest");
  await expect(answer).toContainText("↻ Revised after self-challenge");
  await answer.getByText(/Self-challenge · the objection held/).click();
  const note = answer.getByRole("region", { name: "Self-challenge" });
  await expect(note).toContainText("The excerpt uses hmac.compare_digest, not ==.");
  await note.getByText("The answer before").click();
  await expect(note).toContainText("They are compared with ==");

  // The fact-check waited for the challenge, and checked the final answer.
  await expect(answer.getByRole("region", { name: "Fact-check" })).toContainText("Faithful");
  const tasks = sent.map((b) => b.task ?? "answer");
  expect(tasks).toEqual(["answer", "challenge", "check"]);
  expect(sent[2].answer).toBe(REVISED);

  // Kept with the chat: reopened, nothing is asked again.
  await page.reload();
  await page
    .getByRole("complementary", { name: "Saved chats" })
    .getByRole("button", { name: "How are signatures compared?", exact: true })
    .click();
  await expect(page.getByRole("article", { name: "Answer" })).toContainText("Revised after self-challenge");
  expect(sent).toHaveLength(3);
});
