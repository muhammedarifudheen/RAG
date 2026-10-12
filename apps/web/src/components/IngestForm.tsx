"use client";

import type { IngestResult } from "@atlas/shared";
import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";

import { ingest } from "@/lib/api";

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

export function IngestForm() {
  const [url, setUrl] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const running = useRef(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (running.current) return;
    running.current = true;
    setSteps([]);
    setPhase({ name: "running" });

    try {
      let finished = false;
      for await (const update of ingest(url.trim())) {
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

  const busy = phase.name === "running";

  return (
    <section className="mt-8">
      <form onSubmit={onSubmit} className="flex flex-col gap-2 sm:flex-row">
        <label htmlFor="repo-url" className="sr-only">
          Paste a GitHub repo URL
        </label>
        <input
          id="repo-url"
          type="url"
          required
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="Paste a GitHub repo URL"
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
          {busy ? "Ingesting…" : "Ingest"}
        </button>
      </form>
      <p className="mt-2 text-xs text-slate-500">
        For example https://github.com/pallets/itsdangerous. Ingesting replaces the repository
        that is currently loaded.
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
    </section>
  );
}
