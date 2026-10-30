import type { KnowledgeAudit } from "@atlas/shared";
import { expect, test, type Page } from "@playwright/test";

import { HEALTH, HEALTH_RANKING } from "./fixtures";

// The knowledge-base audit on the Health page: the newest table, and running one as admin.

const OLD: KnowledgeAudit = {
  report:
    "| Source | Coverage | Staleness | Redundancy | Gaps |\n|---|---|---|---|---|\n" +
    "| pallets/itsdangerous | signing | current | none | key rotation? |",
  model: "NVIDIA · nemotron",
  sources: 1,
  created_at: "2026-10-26T06:17:00Z",
};
const NEW: KnowledgeAudit = {
  ...OLD,
  report: OLD.report.replace("key rotation?", "Flask sessions?"),
  sources: 2,
  created_at: "2026-10-30T09:00:00Z",
};

async function mock(page: Page, audit: KnowledgeAudit | null): Promise<string[]> {
  const posted: string[] = [];
  await page.route("**/api/health*", (route) => {
    const request = route.request();
    if (request.method() === "POST") {
      posted.push(request.headers()["authorization"] ?? "");
      return route.fulfill({ json: NEW });
    }
    const ranking = new URL(request.url()).searchParams.has("max_function_loc");
    return route.fulfill({ json: ranking ? HEALTH_RANKING : { ...HEALTH, knowledge_audit: audit } });
  });
  return posted;
}

test("the newest audit is shown as a table, and the admin can run one", async ({ page }) => {
  const posted = await mock(page, OLD);
  await page.goto("/health");
  const audit = page.getByRole("region", { name: "Knowledge-base audit" });
  await expect(audit.getByRole("table")).toContainText("key rotation?");
  await expect(audit).toContainText("1 source audited on");
  await expect(audit).toContainText("by NVIDIA · nemotron");
  // Visitors only read it.
  await expect(audit.getByRole("button", { name: "Run audit now" })).toHaveCount(0);

  await page.evaluate(() => window.localStorage.setItem("atlas-admin-token", "secret"));
  await page.reload();
  await audit.getByRole("button", { name: "Run audit now" }).click();
  await expect(audit.getByRole("table")).toContainText("Flask sessions?");
  await expect(audit).toContainText("2 sources audited on");
  expect(posted).toEqual(["Bearer secret"]);
});

test("without an audit yet, the page says when one runs", async ({ page }) => {
  await mock(page, null);
  await page.goto("/health");
  await expect(page.getByRole("region", { name: "Knowledge-base audit" })).toContainText(
    "No audit yet. One runs every Monday and after each server deploy.",
  );
});
