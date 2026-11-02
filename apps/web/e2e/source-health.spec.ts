import type { IngestPreview, SourceHealthReport, SourceItem, SourceVersion } from "@atlas/shared";
import { expect, test } from "@playwright/test";

import { HEALTH, HEALTH_RANKING, mockHealth, mockSources } from "./fixtures";

// The live knowledge-base health: one score with its history, each source's metrics, and
// an action for each problem. And ingest versions, any of which can be restored.

const REPORT: SourceHealthReport = {
  score: 64,
  answers: 12,
  history: [
    { at: "2026-11-01T00:00:00Z", score: 72 },
    { at: "2026-11-02T00:00:00Z", score: 64 },
  ],
  sources: [
    {
      id: 1,
      title: "A blog",
      kind: "web",
      url: "https://blog.example.com/hmac",
      version: 2,
      score: 48,
      coverage: 0.1,
      freshness: { label: "stale", age_days: 200, trend: "degrading" },
      staleness_risk: 1,
      redundancy: 0.5,
      trust: { weight: 2, label: "secondary", evidence: "blog.example.com: secondary" },
      retrieval: { retrieved: 8, cited: 1, precision: 0.13, mean_relevance: 4.5 },
      gaps: [{ question: "Is HMAC-SHA1 still safe?", suggestion: "https://www.rfc-editor.org/rfc/rfc2104" }],
      actions: [
        { kind: "reingest", label: "Re-ingest", detail: "Preview the changes first." },
        { kind: "demote", label: "Demote to derived", detail: "50% of its passages are also in other sources." },
        {
          kind: "gap",
          label: "Add a source for its gaps",
          detail: "1 question(s) it was retrieved for but could not answer.",
          candidates: ["https://www.rfc-editor.org/rfc/rfc2104"],
        },
        { kind: "chunking", label: "Tune chunking", detail: "Retrieved 8 times but used in only 13%." },
      ],
    },
  ],
};

test("the health page scores the knowledge base and each source, with actions", async ({ page }) => {
  await mockHealth(page, HEALTH, HEALTH_RANKING);
  await page.route("**/api/health/sources", (route) => route.fulfill({ json: REPORT }));
  const preview: IngestPreview = { added: ["web/new"], changed: ["web/hmac"], removed: [], unchanged: 3 };
  await page.route("**/api/sources/1/preview", (route) => route.fulfill({ json: preview }));
  const weights: unknown[] = [];
  await page.route("**/api/sources/1", (route) => {
    weights.push(route.request().postDataJSON());
    return route.fulfill({ json: {} });
  });

  await page.goto("/health");
  await expect(page.getByLabel("Overall health score 64 of 100")).toBeVisible();
  await expect(page.getByRole("img", { name: /from 72 to 64\. ▼ Down 8 since the last check/ })).toBeVisible();
  const actions = page.getByRole("list", { name: "Actions for A blog" });
  await actions.getByRole("button", { name: "Preview changes" }).click();
  await expect(actions.getByLabel("Re-ingest preview")).toContainText("1 added · 1 changed · 0 removed · 3 unchanged");
  await expect(actions.getByRole("link", { name: "Re-ingest now" })).toHaveAttribute(
    "href",
    /\?add=https%3A%2F%2Fblog\.example\.com%2Fhmac$/,
  );
  await expect(actions.getByRole("link", { name: "+ https://www.rfc-editor.org/rfc/rfc2104" })).toBeVisible();
  await actions.getByRole("button", { name: "Demote" }).click();
  await expect.poll(() => weights).toEqual([{ weight: 1 }]);
});

test("a source's kept versions are listed and an older one can be restored", async ({ page }) => {
  const source: SourceItem = {
    id: 7,
    kind: "repo",
    title: "pallets/itsdangerous",
    url: "https://github.com/pallets/itsdangerous",
    created_at: "2026-11-02T10:00:00Z",
    files: 15,
    symbols: 159,
    weight: 3,
    weight_override: null,
    version: 3,
  };
  await mockSources(page, [source]);
  const versions: SourceVersion[] = [
    { version: 3, created_at: "2026-11-02T10:00:00Z", files: 15, symbols: 159, current: true },
    { version: 2, created_at: "2026-10-20T10:00:00Z", files: 14, symbols: 150, current: false },
  ];
  await page.route("**/api/sources/7/versions", (route) => route.fulfill({ json: versions }));
  const restored: unknown[] = [];
  await page.route("**/api/sources/7/rollback", (route) => {
    restored.push(route.request().postDataJSON());
    return route.fulfill({ json: { ...source, version: 4 } });
  });

  await page.goto("/");
  await expect(page.getByText("version 3")).toBeVisible();
  await page.getByRole("button", { name: "Versions of pallets/itsdangerous" }).click();
  const kept = page.getByRole("list", { name: "Kept versions of pallets/itsdangerous" });
  await expect(kept).toContainText("current");
  await kept.getByRole("button", { name: "Restore v2" }).click();
  await expect.poll(() => restored).toEqual([{ version: 2 }]);
});
