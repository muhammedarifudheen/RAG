"use client";

import type { IngestEvent, IngestResult } from "@atlas/shared";
import Link from "next/link";
import { useRef, useState, type ChangeEvent, type FormEvent } from "react";

import { ingest, ingestFile } from "@/lib/api";

import { SourceList } from "./SourceList";

interface Step {
  step: number;
  total: number;
  label: string;
  details: string[];
}

type Phase =
  | { name: "idle" }
  | { name: "running" }
  | { name: "done"; result: IngestResult }
  | { name: "error"; message: string };

const FILE_TYPES = ".pdf,.epub,.txt,.md,.markdown,.html,.htm";
const DEFAULT_CRAWL_PAGES = 20;

export function IngestForm() {
  const [url, setUrl] = useState("");
  const [crawl, setCrawl] = useState(false);
  const [pages, setPages] = useState(DEFAULT_CRAWL_PAGES);
  const [steps, setSteps] = useState<Step[]>([]);
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  // Bumped after each successful ingest so the list of sources reloads.
  const [revision, setRevision] = useState(0);
  const running = useRef(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function run(events: AsyncGenerator<IngestEvent>) {
    if (running.current) return;
    running.current = true;
    setSteps([]);
    setPhase({ name: "running" });

    try {
      let finished = false;
      for await (const update of events) {
        if (update.type === "progress") {
          const { step, total, message } = update;
          setSteps((current) => {
            if (step !== null && total !== null) {
              return [...current, { step, total, label: message, details: [] }];
            }
            const last = current.at(-1);
            if (!last) return current;
            return [...current.slice(0, -1), { ...last, details: [...last.details, message] }];
          });
        } else if (update.type === "done") {
          finished = true;
          setPhase({ name: "done", result: update });
          setRevision((value) => value + 1);
        } else {
          finished = true;
          setPhase({ name: "error", message: update.message });
        }
      }
      if (!finished) {
        setPhase({ name: "error", message: "The connection closed before ingestion finished." });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Ingestion failed.";
      setPhase({ name: "error", message });
    } finally {
      running.current = false;
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(
      ingest(crawl ? { url: url.trim(), kind: "crawl", max_pages: pages } : { url: url.trim() }),
    );
  }

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // so choosing the same file again fires a change
    if (file) void run(ingestFile(file));
  }

  const busy = phase.name === "running";

  return (
    <section className="mt-8">
      <form onSubmit={onSubmit}>
        <div className="flex flex-col gap-2 sm:flex-row">
          <label htmlFor="source-url" className="sr-only">
            Paste a link
          </label>
          <input
            id="source-url"
            type="url"
            required
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="Paste a GitHub repo URL, a Wikipedia article or a web page"
            autoComplete="off"
            spellCheck={false}
            disabled={busy}
            className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 disabled:bg-slate-100"
          />
          <button
            type="submit"
            disabled={busy || url.trim() === ""}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {busy ? "Adding…" : "Add"}
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-slate-600">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={crawl}
              onChange={(event) => setCrawl(event.target.checked)}
              disabled={busy}
              className="h-4 w-4 rounded border-slate-300"
            />
            Follow links on the same site
          </label>
          {crawl && (
            <label className="flex items-center gap-2">
              up to
              <input
                type="number"
                min={1}
                max={100}
                value={pages}
                onChange={(event) => setPages(Number(event.target.value) || DEFAULT_CRAWL_PAGES)}
                disabled={busy}
                aria-label="Maximum pages"
                className="w-16 rounded-md border border-slate-300 px-2 py-1 text-sm"
              />
              pages
            </label>
          )}
          <span className="text-slate-300">|</span>
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={busy}
            className="rounded-md border border-slate-300 bg-white px-3 py-1 text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
          >
            Upload a file
          </button>
          <input
            ref={fileInput}
            type="file"
            accept={FILE_TYPES}
            onChange={onFile}
            aria-label="File to upload"
            className="hidden"
          />
          <span className="text-xs text-slate-500">PDF, EPUB, text, Markdown or HTML</span>
        </div>
      </form>
      <p className="mt-3 text-xs text-slate-500">
        Sources are added to what is already here. Adding one again replaces just that source.
        Only add material you have the right to copy.
      </p>

      {steps.length > 0 && (
        <ol aria-label="Ingest progress" className="mt-6 space-y-3">
          {steps.map((step, index) => {
            const current = busy && index === steps.length - 1;
            const failed = phase.name === "error" && index === steps.length - 1;
            return (
              <li key={step.step} className="flex gap-3 text-sm">
                <span
                  aria-hidden
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                    failed
                      ? "bg-red-100 text-red-700"
                      : current
                        ? "animate-pulse bg-indigo-100 text-indigo-700"
                        : "bg-emerald-100 text-emerald-700"
                  }`}
                >
                  {failed ? "!" : current ? step.step : "✓"}
                </span>
                <div className="min-w-0">
                  <p className="font-medium">
                    {step.label}
                    <span className="ml-2 font-normal text-slate-400">
                      {step.step}/{step.total}
                    </span>
                  </p>
                  {step.details.map((detail, i) => (
                    <p key={i} className="truncate text-xs text-slate-500">
                      {detail}
                    </p>
                  ))}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {phase.name === "error" && (
        <p
          role="alert"
          className="mt-6 whitespace-pre-line rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
        >
          {phase.message}
        </p>
      )}

      {phase.name === "done" && (
        <div
          role="status"
          className="mt-6 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900"
        >
          <p className="font-medium">
            Ingested {phase.result.files} files, {phase.result.symbols} symbols and{" "}
            {phase.result.edges} edges.
          </p>
          <p className="mt-2 flex gap-4">
            <Link href="/chat" className="underline">
              Ask a question
            </Link>
            <Link href="/graph" className="underline">
              View the graph
            </Link>
            <Link href="/health" className="underline">
              Check code health
            </Link>
          </p>
        </div>
      )}

      <SourceList revision={revision} />
    </section>
  );
}
