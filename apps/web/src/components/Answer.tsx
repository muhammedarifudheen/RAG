"use client";

import type { AskResponse, AssistantRoute } from "@atlas/shared";
import { useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  formatRange,
  linkifyCitations,
  parseCitationHref,
  type CodeRange,
} from "@/lib/citations";

interface Props {
  response: AskResponse;
  onCite: (range: CodeRange) => void;
}

export function Answer({ response, onCite }: Props) {
  const markdown = useMemo(() => linkifyCitations(response.answer), [response.answer]);

  const components = useMemo<Components>(() => {
    const unverified = new Set(response.citations.filter((c) => !c.verified).map((c) => c.ref));
    return {
      a({ href, children }) {
        const citation = parseCitationHref(href);
        if (!citation) {
          return (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          );
        }
        const verified = !unverified.has(citation.ref);
        return (
          <button
            type="button"
            onClick={() => onCite(citation)}
            data-verified={verified}
            title={
              verified
                ? "Show this code"
                : "The model was not shown these lines, so this citation is unchecked"
            }
            className={`mx-0.5 rounded border px-1.5 py-0.5 align-baseline font-mono text-[11px] ${
              verified
                ? "border-indigo-200 bg-indigo-50 text-indigo-800 hover:bg-indigo-100"
                : "border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100"
            }`}
          >
            {formatRange(citation)}
            {!verified && <span className="ml-1">(unverified)</span>}
          </button>
        );
      },
    };
  }, [response.citations, onCite]);

  return (
    <article
      aria-label="Answer"
      className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <div className="markdown text-sm leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {markdown}
        </ReactMarkdown>
      </div>

      {!response.complete && (
        <p className="mt-3 text-xs text-amber-700">
          This answer was cut off at the length limit.
        </p>
      )}

      {response.web_sources && response.web_sources.length > 0 && (
        <div className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-600">
          <p className="font-medium text-slate-700">From the web</p>
          <ul className="mt-1 space-y-0.5">
            {response.web_sources.map((source) => (
              <li key={source.url}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-indigo-700 hover:underline"
                >
                  {source.title}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {response.provider && (
        <p className="mt-3 text-[11px] text-slate-400">
          Answered by {response.provider} ({response.model})
          {response.route ? ` · ${ROUTE_LABELS[response.route]}` : ""}
        </p>
      )}

      {response.chunks.length > 0 && (
      <details className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-600">
        <summary className="cursor-pointer select-none">
          {response.chunks.length} code excerpts were given to {response.model}
        </summary>
        <ul className="mt-2 space-y-1">
          {response.chunks.map((chunk) => (
            <li key={chunk.symbol_id}>
              <button
                type="button"
                onClick={() =>
                  onCite({
                    file: chunk.file,
                    startLine: chunk.start_line,
                    endLine: chunk.snippet_end_line,
                  })
                }
                className="text-left hover:text-indigo-700 hover:underline"
              >
                <span className="font-mono">
                  {chunk.file}:{chunk.start_line}-{chunk.snippet_end_line}
                </span>{" "}
                <span className="text-slate-400">
                  {chunk.kind} {chunk.name} · {chunk.score.toFixed(2)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </details>
      )}
    </article>
  );
}

const ROUTE_LABELS: Record<AssistantRoute, string> = {
  sources: "from your sources",
  code: "coding question",
  current: "recent events",
  reasoning: "reasoning question",
  chat: "conversation",
  general: "general question",
};

/** An answer while it is being written: plain Markdown, citations not yet checked. */
export function StreamingAnswer({ text }: { text: string }) {
  return (
    <article
      aria-label="Writing the answer"
      aria-busy="true"
      className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <div className="markdown text-sm leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
      <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-indigo-400 align-middle" />
    </article>
  );
}
