// Visits the public website in a real browser, like a visitor. Not part of the
// test suite (it needs the live server); run it with:  node live-check.mjs
import { chromium } from "@playwright/test";

const SITE = process.env.SITE_URL ?? "https://muhammedarifudheen.github.io/RAG/";
const log = (...args) => console.log(...args);

const browser = await chromium.launch();
const page = await browser.newPage();
const failures = [];
page.on("pageerror", (error) => failures.push(`page error: ${error.message}`));
page.on("console", (message) => {
  if (message.type() === "error") failures.push(`console error: ${message.text()}`);
});

/** Waits for answer number `index`, failing early with the page's message if one appears. */
async function answer(index = 0) {
  const article = page.getByRole("article", { name: "Answer", exact: true }).nth(index);
  // Text only: Next.js puts an empty alert (its route announcer) on every page.
  const alert = page.getByRole("alert").filter({ hasText: /\S/});
  await article.or(alert).first().waitFor({ timeout: 300_000 });
  if (!(await article.isVisible())) throw new Error(`the page said: ${await alert.first().innerText()}`);
  return article;
}

async function check(name, run) {
  const started = Date.now();
  try {
    const detail = await run();
    log(`PASS ${name} (${((Date.now() - started) / 1000).toFixed(1)}s)${detail ? `: ${detail}` : ""}`);
  } catch (error) {
    log(`FAIL ${name}: ${error.message.split("\n")[0]}`);
    failures.push(name);
  }
}

await check("home page lists the sources, managing them is locked", async () => {
  await page.goto(SITE);
  await page.getByText("pallets/itsdangerous").first().waitFor({ timeout: 180_000 });
  const sources = await page.getByRole("listitem").allInnerTexts();
  await page.getByLabel("Admin password").waitFor();
  const removeButtons = await page.getByRole("button", { name: /remove/i }).count();
  if (removeButtons !== 0) throw new Error(`${removeButtons} remove buttons visible to a visitor`);
  return `${sources.length} list items, admin password box shown, no remove buttons`;
});

await check("a wrong admin password is refused", async () => {
  await page.getByLabel("Admin password").fill("not-the-password");
  await page.getByRole("button", { name: "Unlock" }).click();
  await page.getByText("That is not the admin password.").waitFor({ timeout: 60_000 });
});

await check("chat answers with verified citations", async () => {
  await page.goto(new URL("chat/", SITE).href);
  await page.getByLabel("Question").fill("How does itsdangerous check that a signature is valid?");
  await page.getByRole("button", { name: "Ask" }).click();
  const reply = await answer();
  const text = (await reply.innerText()).replace(/\s+/g, " ");
  const citations = reply.locator("button[data-verified]");
  const count = await citations.count();
  const verified = await reply.locator('button[data-verified="true"]').count();
  if (count === 0) throw new Error(`no citations in: ${text.slice(0, 200)}`);
  if (verified !== count) throw new Error(`only ${verified} of ${count} citations verified`);
  await citations.first().click();
  const panel = page.getByRole("complementary", { name: "Cited code" });
  await panel.locator("pre, code").first().waitFor({ timeout: 60_000 });
  return `${verified}/${count} citations verified; the first opens the cited lines. Answer: "${text.slice(0, 150)}…"`;
});

await check("the assistant answers a general question and offers follow-ups", async () => {
  await page.getByRole("button", { name: "+ New chat" }).click();
  await page.getByLabel("Question").fill("What is the capital of Japan? One sentence.");
  await page.getByRole("button", { name: "Ask" }).click();
  const text = (await (await answer()).innerText()).replace(/\s+/g, " ");
  if (!/tokyo/i.test(text)) throw new Error(`no Tokyo in: ${text.slice(0, 200)}`);
  if (/Answered by/.test(text)) throw new Error("the answer names the AI service that wrote it");
  const offered = page.getByRole("group", { name: "Suggested questions" }).getByRole("button");
  await offered.first().waitFor({ timeout: 10_000 });
  return `"${text.slice(0, 80)}"; ${await offered.count()} follow-ups offered`;
});

await check("a suggested follow-up is answered with the conversation", async () => {
  const offered = page.getByRole("group", { name: "Suggested questions" }).getByRole("button");
  const question = await offered.first().innerText();
  await offered.first().click();
  const second = (await (await answer(1)).innerText()).replace(/\s+/g, " ");
  return `asked "${question}"; answer: "${second.slice(0, 120)}…"`;
});

await check("chats are kept in the sidebar", async () => {
  await page.reload();
  const saved = page.getByRole("complementary", { name: "Saved chats" }).getByRole("listitem");
  await saved.first().waitFor({ timeout: 30_000 });
  return `${await saved.count()} saved chats after a reload`;
});

await check("graph page draws the dependency graph", async () => {
  await page.goto(new URL("graph/", SITE).href);
  await page.locator(".react-flow__node").first().waitFor({ timeout: 120_000 });
  return `${await page.locator(".react-flow__node").count()} nodes`;
});

await check("health page shows the dashboard", async () => {
  await page.goto(new URL("health/", SITE).href);
  await page.getByText(/dead|cycle|long functions/i).first().waitFor({ timeout: 120_000 });
});

await browser.close();
const errors = failures.filter((f) => f.startsWith("page error") || f.startsWith("console error"));
log(errors.length ? `browser errors:\n  ${errors.join("\n  ")}` : "browser errors: none");
const failed = failures.filter((f) => !errors.includes(f));
log(failed.length ? `RESULT: ${failed.length} check(s) failed` : "RESULT: all checks passed");
process.exit(failed.length ? 1 : 0);
