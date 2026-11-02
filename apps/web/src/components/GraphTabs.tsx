"use client";

import { useEffect, useState } from "react";

import { FileGraphView } from "./FileGraphView";
import { KnowledgeGraphView } from "./KnowledgeGraphView";

type View = "files" | "knowledge";

/** The graph page: the file dependency graph, or the whole knowledge graph. */
export function GraphTabs() {
  const [view, setView] = useState<View>("files");
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("view") === "knowledge") setView("knowledge");
  }, []);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div role="tablist" aria-label="Graph" className="flex gap-1 border-b border-line bg-panel px-4 pt-2">
        {(
          [
            ["files", "Files"],
            ["knowledge", "Knowledge"],
          ] as [View, string][]
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={view === value}
            onClick={() => setView(value)}
            className={`rounded-t-lg px-3 py-1.5 text-xs ${view === value ? "bg-raised text-paper" : "text-muted hover:text-paper"}`}
          >
            {label}
          </button>
        ))}
      </div>
      {view === "files" ? <FileGraphView /> : <KnowledgeGraphView />}
    </div>
  );
}
