import type { AskRequest, AskResponse, CodeChunk, FactCheck } from "@atlas/shared";
import { expect, test, type Page } from "@playwright/test";

// The fact-checker: its report under a strict answer, and the button under other cited ones.

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
  snippet: "pass",
  snippet_end_line: 240,
  truncated: false,
  citation: "[src/signer.py:227-240]",
};

function reply(answer: string, extra: Partial<AskResponse> = {}): AskResponse {
  return {
    question: "How is a signature checked?",
    answer,
    citations: [{ ref: "[src/signer.py:227-240]", file: "src/signer.py", start_line: 227, end_line: 240, verified: true }],
    chunks: [excerpt],
    model: "m",
    complete: true,
    provider: "Atlas council",
    route: "sources",
    suggestions: [],
    web_sources: [],
    ...extra,
  } as AskResponse;
}

const problems: FactCheck = {
  faithful: false,
  unsupported: ["It uses SHA-512."],
  citation_errors: ["[src/signer.py:900-910] is not in the context"],
  verdict: "One claim is unsupported.",
  checked_by: "NVIDIA · nemotron",
};

async function mock(page: Page, answers: AskResponse[], checks: FactCheck[]): Promise<AskRequest[]> {
  const sent: AskRequest[] = [];
  await page.route("**/api/ask", (route) => {
    const body = route.request().postDataJSON() as AskRequest;
    sent.push(body);
    if (body.task === "check") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(reply(body.answer ?? "", { fact_check: checks.shift() })),
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

async function ask(page: Page, question: string) {
  await page.getByLabel("Question", { exact: true }).fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
}

test("a strict answer asks for its fact-check once shown, and any cited answer can be checked", async ({
  page,
}) => {
  const sent = await mock(
    page,
    [
      reply("It compares in constant time [src/signer.py:227-240].", { fact_check_pending: true }),
      reply("It decodes, then compares [src/signer.py:227-240]."),
    ],
    [
      problems,
      { faithful: true, unsupported: [], citation_errors: [], verdict: "Every claim is cited.", checked_by: "NVIDIA · nemotron" },
    ],
  );
  await page.goto("/chat");
  await ask(page, "How is a signature checked?");
  const first = page.getByRole("article", { name: "Answer" }).first();
  const report = first.getByRole("region", { name: "Fact-check" });
  await expect(report).toContainText("⚠ 2 problems found");
  await expect(report).toContainText("One claim is unsupported.");
  await expect(report.getByRole("list", { name: "Unsupported sentences" })).toContainText("It uses SHA-512.");
  await expect(report.getByRole("list", { name: "Citation errors" })).toContainText("900-910");
  await expect(report).toContainText("Checked by NVIDIA · nemotron");

  await ask(page, "And how is it decoded?");
  const second = page.getByRole("article", { name: "Answer" }).nth(1);
  await expect(second).toContainText("It decodes, then compares");
  await second.getByRole("button", { name: /Fact-check against the sources/ }).click();
  await expect(second.getByRole("region", { name: "Fact-check" })).toContainText("✓ Faithful to the sources");

  const checks = sent.filter((body) => body.task === "check");
  expect(checks.map((c) => c.answer)).toEqual([
    "It compares in constant time [src/signer.py:227-240].",
    "It decodes, then compares [src/signer.py:227-240].",
  ]);
  expect(checks[1].chunks?.[0].file).toBe("src/signer.py");

  // Kept with the answer: a reload shows the report without checking again.
  await page.reload();
  await page
    .getByRole("complementary", { name: "Saved chats" })
    .getByRole("button", { name: "How is a signature checked?", exact: true })
    .click();
  await expect(
    page.getByRole("article", { name: "Answer" }).first().getByRole("region", { name: "Fact-check" }),
  ).toContainText("⚠ 2 problems found");
  expect(sent.filter((body) => body.task === "check")).toHaveLength(2);
});
