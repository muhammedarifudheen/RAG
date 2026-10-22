"use client";

import { useEffect, useRef, useState } from "react";

import { getFile } from "@/lib/api";
import { formatRange, type CodeRange } from "@/lib/citations";
import { highlightCode, shikiLanguage } from "@/lib/highlight";
import { useApi } from "@/lib/useApi";

interface Props {
  range: CodeRange;
  onClose: () => void;
}

/** Side panel showing a whole file with the cited lines marked and scrolled into view. */
export function CodePanel({ range, onClose }: Props) {
  const file = useApi(() => getFile(range.file), range.file);
  const [html, setHtml] = useState<string | null>(null);
  const container = useRef<HTMLDivElement>(null);

  const content = file.status === "ready" ? file.data.content : null;
  const language = file.status === "ready" ? file.data.language : "";

  useEffect(() => {
    setHtml(null);
    if (content === null) return;
    let current = true;
    highlightCode(content, shikiLanguage(range.file, language), range).then((result) => {
      if (current) setHtml(result);
    });
    return () => {
      current = false;
    };
  }, [content, language, range]);

  useEffect(() => {
    if (html === null) return;
    container.current?.querySelector(".cited")?.scrollIntoView({ block: "center" });
  }, [html]);

  return (
    <aside
      aria-label="Cited code"
      className="sticky top-0 flex h-[calc(100vh-3.5rem)] w-[min(46rem,50vw)] shrink-0 flex-col border-l border-line bg-panel"
    >
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
        <h2 className="truncate font-mono text-xs font-semibold">{formatRange(range)}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close code panel"
          className="px-2 py-1 text-sm text-muted hover:bg-raised hover:text-paper"
        >
          ✕
        </button>
      </header>

      <div ref={container} className="min-h-0 flex-1 overflow-auto">
        {file.status === "error" && (
          <p role="alert" className="p-4 text-sm text-danger">
            {file.message}
          </p>
        )}
        {file.status !== "error" && html === null && (
          <p role="status" className="p-4 text-sm text-muted">
            Loading {range.file}…
          </p>
        )}
        {html !== null && (
          // Shiki escapes the source text; the markup is its own token spans.
          <div className="code-view" dangerouslySetInnerHTML={{ __html: html }} />
        )}
      </div>
    </aside>
  );
}
