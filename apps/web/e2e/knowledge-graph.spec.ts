import type { KgGraph, KgNodeDetail } from "@atlas/shared";
import { expect, test } from "@playwright/test";

// The knowledge graph: drawn clustered by source, shaped and coloured by type; a node's
// side panel with its snippet, citation and edges; questions in words; "Ask about this".

const GRAPH: KgGraph = {
  nodes: [
    { id: "symbol:1", label: "Signer.unsign", type: "method", source_id: 1, source: "pallets/itsdangerous", citation: "[a/signer.py:10-20]" },
    { id: "symbol:2", label: "verify_signature", type: "method", source_id: 1, source: "pallets/itsdangerous", citation: "[a/signer.py:30-40]" },
    { id: "concept:3", label: "HMAC", type: "concept", source_id: null, source: null },
    { id: "person:4", label: "Mihir Bellare", type: "person", source_id: null, source: null },
  ],
  edges: [
    { source: "symbol:1", target: "symbol:2", kind: "calls", confidence: 1, evidence: null },
    { source: "concept:3", target: "symbol:2", kind: "mentioned_in", confidence: 0.7, evidence: "[docs/hmac.md:1-4]" },
  ],
  truncated: false,
};

const DETAIL: KgNodeDetail = {
  ...GRAPH.nodes[1],
  snippet: "def verify_signature(self, key, value, sig):\n    return compare_digest(sig, expected)",
  edges: [{ kind: "calls", direction: "in", other: GRAPH.nodes[0], confidence: 1, evidence: null }],
};

test("the knowledge graph is drawn, and a node opens with its snippet and edges", async ({ page }) => {
  await page.route("**/api/kg/overview*", (route) => route.fulfill({ json: GRAPH }));
  await page.route("**/api/kg/node*", (route) => route.fulfill({ json: DETAIL }));
  const path: KgGraph = {
    ...GRAPH,
    path: ["symbol:1", "symbol:2"],
    answer: "**Shortest path (1 steps):**\n\n`Signer.unsign` —calls→ `verify_signature`",
  };
  await page.route("**/api/kg/ask*", (route) => route.fulfill({ json: path }));

  await page.goto("/graph?view=knowledge");
  await expect(page.getByRole("tab", { name: "Knowledge" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("img", { name: "Knowledge graph of 4 nodes, clustered by source" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Legend" })).toContainText("Person");
  await page.getByRole("button", { name: "Code verify_signature" }).click();
  const panel = page.getByRole("complementary", { name: "Node" });
  await expect(panel).toContainText("[a/signer.py:30-40]");
  await expect(panel).toContainText("def verify_signature");
  await expect(panel.getByRole("list", { name: "Edges" })).toContainText("calls");
  await expect(panel.getByRole("link", { name: "Ask about this" })).toHaveAttribute(
    "href",
    /\/chat\?ask=Tell%20me%20about%20verify_signature/,
  );

  await page.getByLabel("Ask the graph").fill("shortest path between Signer.unsign and verify_signature");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Shortest path (1 steps)");
});

test("ask about this writes the question into the chat, unsent", async ({ page }) => {
  await page.goto("/chat?ask=Tell%20me%20about%20verify_signature");
  await expect(page.getByLabel("Question", { exact: true })).toHaveValue("Tell me about verify_signature");
});
