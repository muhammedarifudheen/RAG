import type { FileGraph } from "@atlas/shared";
import { expect, test } from "@playwright/test";

import { FILE_GRAPH, MODELS_FILE, mockFiles } from "./fixtures";

test("draws files as nodes and dependencies as edges, with cycles in red", async ({ page }) => {
  await page.route("**/api/graph/files", (route) => route.fulfill({ json: FILE_GRAPH }));

  await page.goto("/graph");

  const nodes = page.locator(".react-flow__node");
  await expect(nodes).toHaveCount(4);
  await expect(page.getByTestId("graph-summary")).toHaveText("4 files · 3 dependencies · 1 cycle");
  for (const path of ["pkg/models.py", "pkg/service.py", "pkg/cycle_a.py", "pkg/cycle_b.py"]) {
    await expect(nodes.filter({ hasText: path })).toHaveCount(1);
  }

  // The two files in the cycle, and both edges between them, are red.
  const inCycle = page.locator(".react-flow__node.in-cycle");
  await expect(inCycle).toHaveCount(2);
  await expect(inCycle.filter({ hasText: "pkg/cycle_a.py" })).toHaveCount(1);
  await expect(inCycle.filter({ hasText: "pkg/cycle_b.py" })).toHaveCount(1);
  await expect(inCycle.first()).toHaveCSS("border-color", "rgb(220, 38, 38)");
  await expect(nodes.filter({ hasText: "pkg/models.py" })).toHaveCSS(
    "border-color",
    "rgb(203, 213, 225)",
  );

  const edges = page.locator(".react-flow__edge");
  await expect(edges).toHaveCount(3);
  const cycleEdges = page.locator(".react-flow__edge.in-cycle .react-flow__edge-path");
  await expect(cycleEdges).toHaveCount(2);
  await expect(cycleEdges.first()).toHaveCSS("stroke", "rgb(220, 38, 38)");
  await expect(
    page.locator(".react-flow__edge:not(.in-cycle) .react-flow__edge-path"),
  ).toHaveCSS("stroke", "rgb(148, 163, 184)");
});

test("the layout spreads nodes out instead of stacking them", async ({ page }) => {
  await page.route("**/api/graph/files", (route) => route.fulfill({ json: FILE_GRAPH }));

  await page.goto("/graph");
  await expect(page.locator(".react-flow__node")).toHaveCount(4);

  const boxes = await page
    .locator(".react-flow__node")
    .evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().toJSON() as DOMRect));
  for (let a = 0; a < boxes.length; a++) {
    for (let b = a + 1; b < boxes.length; b++) {
      const apart =
        boxes[a].right <= boxes[b].left ||
        boxes[b].right <= boxes[a].left ||
        boxes[a].bottom <= boxes[b].top ||
        boxes[b].bottom <= boxes[a].top;
      expect(apart, `nodes ${a} and ${b} overlap`).toBe(true);
    }
  }
});

test("clicking a node lists the symbols in that file", async ({ page }) => {
  await page.route("**/api/graph/files", (route) => route.fulfill({ json: FILE_GRAPH }));
  await mockFiles(page, [MODELS_FILE]);

  await page.goto("/graph");
  const panel = page.getByRole("complementary", { name: "File symbols" });
  await expect(panel).toHaveText("Click a file to see its symbols.");
  const canvas = page.getByTestId("file-graph");
  const widthBefore = (await canvas.boundingBox())?.width;

  await page.locator(".react-flow__node").filter({ hasText: "pkg/models.py" }).click();

  // The panel reserves its space, so opening it does not resize the graph.
  expect((await canvas.boundingBox())?.width).toBe(widthBefore);

  await expect(panel.getByRole("heading")).toHaveText("pkg/models.py");
  await expect(panel).toContainText("python · 21 lines");
  const symbols = panel.getByRole("listitem");
  await expect(symbols).toHaveCount(3);
  await expect(symbols.nth(0)).toContainText("class");
  await expect(symbols.nth(0)).toContainText("Base");
  await expect(symbols.nth(2)).toContainText("format_name");
  await expect(symbols.nth(2)).toContainText("lines 20–21");
  await expect(panel).not.toContainText("in a cycle");

  // Selecting a file that is part of a cycle says so.
  await page.locator(".react-flow__node").filter({ hasText: "pkg/cycle_a.py" }).click();
  await expect(panel.getByRole("heading")).toHaveText("pkg/cycle_a.py");
  await expect(panel).toContainText("in a cycle");

  await panel.getByRole("button", { name: "Close file panel" }).click();
  await expect(panel).toHaveText("Click a file to see its symbols.");
});

test("explains an empty graph", async ({ page }) => {
  const empty: FileGraph = { nodes: [], edges: [], cycles: [] };
  await page.route("**/api/graph/files", (route) => route.fulfill({ json: empty }));

  await page.goto("/graph");

  await expect(page.getByText("No repository has been ingested yet.")).toBeVisible();
  await page.getByRole("link", { name: "Ingest one" }).click();
  await expect(page).toHaveURL(/\/$/);
});
