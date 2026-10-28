import type { AskRequest, AskResponse, CodeAnalysis } from "@atlas/shared";
import { expect, test, type Route } from "@playwright/test";

// The code analyser: real checks on a repository or pasted code, then the council's review.

const ANALYSIS: CodeAnalysis = {
  repo: "https://github.com/pallets/itsdangerous",
  commit: "abc1234def5678",
  files: 12,
  lines: 2400,
  code_lines: 1800,
  languages: { python: 1700, md: 600, toml: 100 },
  score: 72,
  grade: "C",
  counts: { high: 1, medium: 2, low: 3 },
  findings: [
    {
      tool: "ruff",
      rule: "S307",
      severity: "high",
      path: "src/signer.py",
      line: 42,
      message: "Use of possibly insecure function; consider using `ast.literal_eval`",
    },
    {
      tool: "complexity",
      rule: "too-complex",
      severity: "medium",
      path: "src/serializer.py",
      line: 10,
      message: "Serializer.loads has cyclomatic complexity 18 over 60 lines; split it.",
    },
    {
      tool: "ruff",
      rule: "B006",
      severity: "medium",
      path: "src/url_safe.py",
      line: 5,
      message: "Do not use mutable data structures for argument defaults",
    },
    { tool: "ruff", rule: "F401", severity: "low", path: "src/a.py", line: 1, message: "`os` unused" },
    { tool: "patterns", rule: "todo", severity: "low", path: "src/b.py", line: 9, message: "TODO: x" },
    { tool: "ruff", rule: "F841", severity: "low", path: "src/c.py", line: 3, message: "unused var" },
  ],
  functions: [
    {
      path: "src/serializer.py",
      name: "Serializer.loads",
      start_line: 10,
      end_line: 69,
      complexity: 18,
      nesting: 3,
    },
  ],
  test_files: 4,
  cycles: [["src/a.py", "src/b.py"]],
  most_imported: [{ path: "src/signer.py", imported_by: 5 }],
  riskiest: [
    { path: "src/signer.py", lines: 300, findings: 1, complexity: 12, imported_by: 5, risk: 25.8 },
  ],
  seconds: 3.2,
};

const REVIEW = "**Verdict**: solid, but `src/signer.py:42` calls `eval`.";

function done(question: string, extra: Partial<AskResponse> = {}): AskResponse {
  return {
    question,
    answer: REVIEW,
    citations: [],
    chunks: [],
    model: "claude-opus-5-5",
    complete: true,
    provider: "Atlas council",
    route: "review",
    suggestions: [],
    web_sources: [],
    analysis: ANALYSIS,
    ...extra,
  };
}

function stream(route: Route, events: [string, unknown][]) {
  return route.fulfill({
    status: 200,
    headers: { "content-type": "text/event-stream" },
    body: events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join(""),
  });
}

test("a repository is analysed and the council's review follows the report", async ({ page }) => {
  const sent: AskRequest[] = [];
  await page.route("**/api/ask", (route) => {
    const body = route.request().postDataJSON() as AskRequest;
    sent.push(body);
    return stream(route, [
      ["analysing", { message: "Analysing https://github.com/pallets/itsdangerous" }],
      ["analysing", { message: "Cloning the repository" }],
      ["analysis", ANALYSIS],
      ["route", { route: "review", mode: "auto", providers: ["claude"] }],
      ["delta", { text: REVIEW }],
      ["done", done(body.question)],
    ]);
  });

  await page.goto("/analyze");
  await expect(page.getByRole("heading", { name: "Analyse a repository" })).toBeVisible();
  await page.getByLabel("GitHub repository").fill("https://github.com/pallets/itsdangerous");
  await page.getByRole("button", { name: "Analyse", exact: true }).click();

  const report = page.getByRole("region", { name: "Code analysis" });
  await expect(report.getByLabel("Grade C")).toBeVisible();
  await expect(report).toContainText("72/100");
  await expect(report).toContainText("1,800 lines of code");
  await expect(report).toContainText("pallets/itsdangerous");
  await expect(report).toContainText("src/a.py ↔ src/b.py");
  await expect(report.getByRole("table")).toContainText("src/signer.py");
  await expect(report).toContainText("Serializer.loads");

  const findings = report.getByRole("list", { name: "Findings", exact: true });
  await expect(findings.getByRole("listitem")).toHaveCount(6);
  await report.getByRole("button", { name: "high", exact: true }).click();
  await expect(findings.getByRole("listitem")).toHaveCount(1);
  await expect(findings).toContainText("src/signer.py:42");

  const review = page.getByRole("region", { name: "Review" });
  await expect(review.getByRole("article", { name: "Answer" })).toContainText("calls eval");
  expect(sent[0].task).toBe("review");
  expect(sent[0].question).toContain("https://github.com/pallets/itsdangerous");
});

test("an address that is not a GitHub repository is refused before anything is sent", async ({
  page,
}) => {
  let asked = false;
  await page.route("**/api/ask", (route) => {
    asked = true;
    return route.abort();
  });
  await page.goto("/analyze");
  await page.getByLabel("GitHub repository").fill("https://example.com/code");
  await page.getByRole("button", { name: "Analyse", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "public GitHub repository" })).toBeVisible();
  expect(asked).toBe(false);
});

test("a code review in chat carries the analyser's report under the answer", async ({ page }) => {
  await page.route("**/api/ask", (route) => {
    const body = route.request().postDataJSON() as AskRequest;
    return stream(route, [
      ["analysing", { message: "Running the code analyser on 1 file(s)" }],
      ["analysis", { ...ANALYSIS, repo: null, commit: null }],
      ["route", { route: "review", mode: "auto", providers: ["claude"] }],
      ["delta", { text: REVIEW }],
      ["done", done(body.question, { analysis: { ...ANALYSIS, repo: null, commit: null } })],
    ]);
  });
  await page.goto("/chat");
  await page.getByLabel("Question").fill("Review this:\n```python\neval(x)\n```");
  await page.getByRole("button", { name: "Ask" }).click();

  const answer = page.getByRole("article", { name: "Answer" });
  await expect(answer).toContainText("calls eval");
  await answer.getByText("Code analysis: grade C, 72/100").click();
  await expect(answer.getByRole("region", { name: "Code analysis" })).toContainText(
    "src/signer.py:42",
  );
});
