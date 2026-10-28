"use client";

import type { AskResponse, CodeAnalysis } from "@atlas/shared";
import { useEffect, useRef, useState } from "react";

import { askAssistant } from "@/lib/api";

import { AnalysisReport } from "./AnalysisReport";
import { Answer, StreamingAnswer } from "./Answer";

const REPO = /^https:\/\/github\.com\/[A-Za-z0-9][\w.-]*\/[\w.-]+\/?$/;
const EXAMPLES = [
  "https://github.com/pallets/itsdangerous",
  "https://github.com/pallets/click",
  "https://github.com/encode/uvicorn",
];

type Phase = "idle" | "running" | "done" | "error";

/** Analyses a public GitHub repository: real checks first, then the council's review. */
export function RepoAnalyzer() {
  const [url, setUrl] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [steps, setSteps] = useState<string[]>([]);
  const [analysis, setAnalysis] = useState<CodeAnalysis | null>(null);
  const [streaming, setStreaming] = useState("");
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  async function analyse(target: string) {
    const repo = target.trim().replace(/\.git$/, "");
    if (!REPO.test(repo)) {
      setPhase("error");
      setError("Enter a public GitHub repository's address, like https://github.com/owner/name.");
      return;
    }
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setUrl(repo);
    setPhase("running");
    setSteps([]);
    setAnalysis(null);
    setStreaming("");
    setResponse(null);
    setError("");
    try {
      const done = await askAssistant(
        {
          question: `Review the code of ${repo}: its bugs, security problems, complexity and design.`,
          history: [],
          mode: "auto",
          task: "review",
        },
        {
          onAnalysing: (message) => setSteps((current) => [...current, message]),
          onAnalysis: setAnalysis,
          onDelta: (piece) => setStreaming((current) => current + piece),
          onReset: () => setStreaming(""),
        },
        abort.signal,
      );
      if (abort.signal.aborted) return;
      setResponse(done);
      if (done.analysis) setAnalysis(done.analysis);
      setPhase("done");
    } catch (caught) {
      if (abort.signal.aborted) return;
      setPhase("error");
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <p className="label flex items-center gap-3 text-muted">
        <span className="bg-signal px-1.5 py-0.5 text-ink">05</span>
        Code analyser
        <span aria-hidden="true" className="h-px flex-1 bg-line" />
      </p>
      <h1 className="mt-5 font-display text-3xl font-semibold tracking-tight sm:text-4xl">
        Analyse a repository
      </h1>
      <p className="mt-3 max-w-2xl text-sm text-soft">
        Atlas clones a public GitHub repository and runs real checks on it: Ruff&apos;s bug and
        security rules for Python, a scan for leaked secrets, risky patterns in JavaScript,
        TypeScript and Go, the complexity of every function, and its import cycles. Then the
        council of AI agents reviews what they found, with fixes. Nothing is stored.
      </p>

      <form
        className="mt-6 flex flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          void analyse(url);
        }}
      >
        <label htmlFor="repo" className="sr-only">
          GitHub repository
        </label>
        <input
          id="repo"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://github.com/owner/name"
          className="min-w-0 flex-1 border border-line bg-ink px-3 py-2 font-mono text-sm outline-none placeholder:text-faint focus:border-signal"
        />
        <button
          type="submit"
          disabled={phase === "running"}
          className="bg-signal px-5 py-2 font-mono text-[12px] font-bold uppercase tracking-[0.16em] text-ink disabled:opacity-50"
        >
          {phase === "running" ? "Working…" : "Analyse"}
        </button>
      </form>
      <ul aria-label="Examples" className="mt-2 flex flex-wrap gap-2">
        {EXAMPLES.map((example) => (
          <li key={example}>
            <button
              type="button"
              disabled={phase === "running"}
              onClick={() => void analyse(example)}
              className="border border-line px-2 py-0.5 font-mono text-[11px] text-muted hover:border-cyan/60 hover:text-cyan"
            >
              {example.replace("https://github.com/", "")}
            </button>
          </li>
        ))}
      </ul>

      {phase === "error" && (
        <p role="alert" className="mt-6 border border-danger/40 bg-danger/10 p-4 text-sm text-danger">
          {error}
        </p>
      )}

      {phase === "running" && (
        <div role="status" className="slab mt-6 py-2 pl-4 text-sm text-muted">
          <p className="animate-pulse">
            {analysis
              ? `Analysed: grade ${analysis.grade}. The council is writing its review…`
              : (steps.at(-1) ?? "Starting…") + "…"}
          </p>
          {steps.length > 1 && (
            <ol className="mt-1 list-inside list-decimal font-mono text-[11px] text-faint">
              {steps.slice(0, -1).map((step, index) => (
                <li key={`${index}:${step}`}>{step}</li>
              ))}
            </ol>
          )}
        </div>
      )}

      {analysis && (
        <div className="mt-8 border border-line bg-panel/60 p-4 sm:p-6">
          <AnalysisReport analysis={analysis} />
        </div>
      )}

      {(streaming || response) && (
        <section aria-label="Review" className="mt-8">
          <h2 className="label text-muted">The council&apos;s review</h2>
          <div className="mt-3">
            {response ? (
              <Answer response={{ ...response, analysis: null }} onCite={() => undefined} />
            ) : (
              <StreamingAnswer text={streaming} />
            )}
          </div>
        </section>
      )}
    </div>
  );
}
