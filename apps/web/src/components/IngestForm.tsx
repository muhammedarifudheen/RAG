"use client";

import type { IngestEvent, IngestResult } from "@atlas/shared";
import Link from "next/link";
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";

import {
  ApiError,
  checkAdmin,
  getAdminToken,
  getConfig,
  ingest,
  ingestFile,
  setAdminToken,
} from "@/lib/api";
import { useApi } from "@/lib/useApi";

import { AdminUnlock } from "./AdminUnlock";
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
  // "Add this source" from the gap finder links here with ?add=<address>.
  useEffect(() => {
    const suggested = new URLSearchParams(window.location.search).get("add");
    if (suggested) setUrl(suggested);
  }, []);
  const [crawl, setCrawl] = useState(false);
  const [pages, setPages] = useState(DEFAULT_CRAWL_PAGES);
  const [steps, setSteps] = useState<Step[]>([]);
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  // Bumped after each successful ingest so the list of sources reloads.
  const [revision, setRevision] = useState(0);
  const running = useRef(false);
  const fileInput = useRef<HTMLInputElement>(null);

  // A public deployment requires the admin password to manage sources.
  const config = useApi(getConfig);
  const [unlocked, setUnlocked] = useState(false);
  useEffect(() => {
    const token = getAdminToken();
    if (!token) return;
    // A remembered password may have been changed on the server since.
    checkAdmin(token).then(
      (valid) => (valid ? setUnlocked(true) : setAdminToken(null)),
      () => undefined,
    );
  }, []);
  const adminRequired = config.status === "ready" && config.data.admin_required;
  const canManage = !adminRequired || unlocked;

  function lock() {
    setAdminToken(null);
    setUnlocked(false);
  }

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
      if (error instanceof ApiError && error.status === 401) lock();
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

  if (!canManage) {
    return (
      <>
        <AdminUnlock onUnlock={() => setUnlocked(true)} />
        <SourceList revision={revision} canManage={false} />
      </>
    );
  }

  return (
    <section className="mt-8">
      {adminRequired && (
        <p className="mb-3 text-xs text-muted">
          Signed in as admin.{" "}
          <button type="button" onClick={lock} className="text-cyan underline">
            Lock
          </button>
        </p>
      )}
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
            className="min-w-0 flex-1 border border-line-strong bg-ink px-3 py-2 text-sm shadow-sm outline-none focus:border-signal focus:ring-2 focus:ring-signal/30 disabled:bg-raised"
          />
          <button
            type="submit"
            disabled={busy || url.trim() === ""}
            className="bg-signal px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-signal-hover disabled:cursor-not-allowed disabled:bg-raised"
          >
            {busy ? "Adding…" : "Add"}
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-soft">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={crawl}
              onChange={(event) => setCrawl(event.target.checked)}
              disabled={busy}
              className="h-4 w-4 border-line-strong"
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
                className="w-16 border border-line-strong bg-ink px-2 py-1 text-sm"
              />
              pages
            </label>
          )}
          <span className="text-faint">|</span>
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={busy}
            className="border border-line-strong bg-panel px-3 py-1 text-sm hover:bg-raised disabled:cursor-not-allowed disabled:text-faint"
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
          <span className="text-xs text-muted">PDF, EPUB, text, Markdown or HTML</span>
        </div>
      </form>
      <p className="mt-3 text-xs text-muted">
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
                      ? "bg-danger/15 text-danger"
                      : current
                        ? "animate-pulse bg-signal/20 text-cyan"
                        : "bg-ok/15 text-ok"
                  }`}
                >
                  {failed ? "!" : current ? step.step : "✓"}
                </span>
                <div className="min-w-0">
                  <p className="font-medium">
                    {step.label}
                    <span className="ml-2 font-normal text-muted">
                      {step.step}/{step.total}
                    </span>
                  </p>
                  {step.details.map((detail, i) => (
                    <p key={i} className="truncate text-xs text-muted">
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
          className="mt-6 whitespace-pre-line border border-danger/40 bg-danger/10 p-4 text-sm text-danger"
        >
          {phase.message}
        </p>
      )}

      {phase.name === "done" && (
        <div
          role="status"
          className="mt-6 border border-ok/40 bg-ok/10 p-4 text-sm text-ok"
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

      <SourceList revision={revision} canManage />
    </section>
  );
}
