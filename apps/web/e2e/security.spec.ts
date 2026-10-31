import type { AskResponse, SiteConfig, SourceItem } from "@atlas/shared";
import { expect, test } from "@playwright/test";

// Security: an authenticator unlock gives a session whose key signs source changes; the
// chat is grounded unless the web is allowed; redactions are shown.

const SOURCE: SourceItem = {
  id: 7,
  kind: "repo",
  title: "pallets/itsdangerous",
  url: "https://github.com/pallets/itsdangerous",
  created_at: "2026-10-30T10:00:00Z",
  files: 15,
  symbols: 159,
};

test("with an authenticator, unlocking asks for its code and source changes are signed", async ({
  page,
}) => {
  const config: SiteConfig = { admin_required: true, chat_configured: true, admin_mfa: true };
  await page.route("**/api/config", (route) => route.fulfill({ json: config }));
  const checks: { auth?: string; body: string | null }[] = [];
  await page.route("**/api/admin/check", (route) => {
    const request = route.request();
    checks.push({ auth: request.headers()["authorization"], body: request.postData() });
    return route.fulfill({
      json: { session: "s1", key: "00".repeat(32), expires_at: Date.now() / 1000 + 3600 },
    });
  });
  const sources = [SOURCE];
  await page.route("**/api/sources", (route) => route.fulfill({ json: sources }));
  const deletes: Record<string, string>[] = [];
  await page.route("**/api/sources/7", (route) => {
    deletes.push(route.request().headers());
    sources.splice(0, 1);
    return route.fulfill({ status: 204 });
  });

  await page.goto("/");
  await page.getByLabel("Admin password").fill("pw");
  const unlock = page.getByRole("button", { name: "Unlock" });
  await expect(unlock).toBeDisabled(); // the code is needed too
  await page.getByLabel("Authenticator code").fill("123456");
  await unlock.click();
  await page.getByRole("button", { name: "Remove pallets/itsdangerous" }).click();
  await expect.poll(() => deletes.length).toBe(1);

  expect(checks[0]).toEqual({ auth: "Bearer pw", body: JSON.stringify({ code: "123456" }) });
  const signed = deletes[0];
  expect(signed["x-atlas-session"]).toBe("s1");
  expect(signed["x-atlas-timestamp"]).toMatch(/^\d{10}$/);
  expect(signed["x-atlas-signature"]).toMatch(/^[0-9a-f]{64}$/);
});

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

test("the chat is grounded unless the web is allowed, and redactions are shown", async ({
  page,
}) => {
  const open: string[] = [];
  const answers = [
    reply("I don't have that in the knowledge base.", { epistemic: "absent", grounded: true }),
    reply("Canberra. Contact [redacted email].", { epistemic: "web", redacted: ["email"] }),
  ];
  await page.route("**/api/ask", (route) => {
    // The absent answer asks the gap finder, which is not one of these answers.
    if ((route.request().postDataJSON() as { task?: string }).task === "gaps") {
      const gaps = { report: "2. Missing: geography.", suggestion_url: null, found_by: "x" };
      return route.fulfill({ json: reply(gaps.report, { gaps }) });
    }
    open.push(route.request().headers()["x-atlas-open"] ?? "");
    const next = answers.shift() ?? reply("…");
    return route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body:
        `event: route\ndata: ${JSON.stringify({ route: "general", mode: "auto", providers: ["groq"] })}\n\n` +
        `event: done\ndata: ${JSON.stringify(next)}\n\n`,
    });
  });
  await page.goto("/chat");
  const web = page.getByRole("button", { name: "Allow web and general knowledge" });
  await expect(web).toHaveAttribute("aria-pressed", "false");
  await expect(web).toContainText("Grounded");
  await page.getByLabel("Question", { exact: true }).fill("What is the capital of Australia?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByRole("article", { name: "Answer" })).toContainText("knowledge base");

  await web.click();
  await expect(web).toContainText("Web on");
  await page.getByLabel("Question", { exact: true }).fill("And now?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const second = page.getByRole("article", { name: "Answer" }).nth(1);
  await expect(second).toContainText("🔒 Redacted: email");
  expect(open).toEqual(["", "true"]);
});
