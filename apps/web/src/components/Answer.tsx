"use client";

import type {
  AskResponse,
  CodeChunk,
  Confidence,
  EpistemicState,
  FactCheck,
  GapReport,
  GeneratedImage,
  SelfChallenge,
  ResearchStep,
} from "@atlas/shared";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import {
  formatRange,
  linkifyCitations,
  parseCitationHref,
  type CodeRange,
} from "@/lib/citations";
import { challengeAnswer, factCheck, findGaps } from "@/lib/api";
import { copyText } from "@/lib/exporting";
import { normalizeMath } from "@/lib/markdown";

import { AnalysisReport } from "./AnalysisReport";

interface Props {
  response: AskResponse;
  onCite: (range: CodeRange) => void;
  /** A fact-check finished, to keep with the answer. */
  onFactChecked?: (report: FactCheck) => void;
  /** The gap finder reported, to keep with the answer. */
  onGapsFound?: (gaps: GapReport) => void;
  /** The self-challenge finished: the final answer and its report, to keep. */
  onChallenged?: (result: AskResponse) => void;
}

const REMARK = [remarkGfm, remarkMath];
const REHYPE = [rehypeKatex];

export function Answer({ response, onCite, onFactChecked, onGapsFound, onChallenged }: Props) {
  const markdown = useMemo(
    () => normalizeMath(linkifyCitations(response.answer)),
    [response.answer],
  );

  const components = useMemo<Components>(() => {
    const unverified = new Set(response.citations.filter((c) => !c.verified).map((c) => c.ref));
    return {
      pre: CodePre,
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
            aria-label={`${formatRange(citation)}${verified ? "" : " (unverified)"}: citation, shows the cited lines`}
            title={
              verified
                ? "Show this code"
                : "The model was not shown these lines, so this citation is unchecked"
            }
            className={`mx-0.5 border px-1.5 py-0.5 align-baseline font-mono text-[11px] transition-colors ${
              verified
                ? "border-cyan/40 bg-cyan/10 text-cyan hover:bg-cyan/20"
                : "border-warn/50 bg-warn/10 text-warn hover:bg-warn/20"
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
    <article aria-label="Answer" className="slab bg-panel/80 py-4 pl-5 pr-4">
      {(response.epistemic || response.challenge?.valid || response.source_basis) && (
        <p className="mb-2 flex flex-wrap items-center gap-2">
          {response.epistemic && <EpistemicBadge state={response.epistemic} />}
          {(response.source_basis === "secondary" || response.source_basis === "derived") && (
            <span
              role="note"
              aria-label="Based on secondary sources only: no primary source (code, spec or official docs) was found."
              title="No primary source (code, spec or official docs) was found."
              className="label rounded-full border border-warn/40 bg-warn/10 px-2.5 py-0.5 text-warn"
            >
              Secondary sources only
            </span>
          )}
          {response.challenge?.valid && (
            <span className="label rounded-full border border-signal/40 bg-signal/10 px-2.5 py-0.5 text-signal">
              ↻ Revised after self-challenge
            </span>
          )}
        </p>
      )}
      <div className="markdown text-[15px] leading-relaxed">
        <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={REHYPE} components={components}>
          {markdown}
        </ReactMarkdown>
      </div>

      {(response.confidence || response.cached || response.notice) && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          {response.confidence && <ConfidenceBadge confidence={response.confidence} />}
          {response.cached && (
            <span className="rounded-full border border-line px-2 py-0.5 text-muted">
              ↺ Asked before: the answer from then
            </span>
          )}
          {response.notice && <span className="text-warn">{response.notice}</span>}
        </p>
      )}

      {response.images && response.images.length > 0 && <Gallery images={response.images} />}

      <ChallengePanel response={response} onDone={onChallenged} />
      <FactCheckPanel response={response} onChecked={onFactChecked} />
      <GapsPanel response={response} onFound={onGapsFound} />

      {response.analysis && (
        <details className="mt-4 border-t border-line pt-3">
          <summary className="cursor-pointer select-none text-sm text-muted hover:text-paper">
            Code analysis: grade {response.analysis.grade}, {response.analysis.score}/100,{" "}
            {response.analysis.counts.high} high · {response.analysis.counts.medium} medium ·{" "}
            {response.analysis.counts.low} low
          </summary>
          <div className="mt-3">
            <AnalysisReport analysis={response.analysis} />
          </div>
        </details>
      )}

      {response.drafts && response.drafts.length > 0 && (
        <details className="mt-4 border-t border-line pt-3">
          <summary className="cursor-pointer select-none text-sm text-muted hover:text-paper">
            {response.drafts.length} agent drafts, before the merge
          </summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {response.drafts.map((draft) => (
              <section
                key={draft.agent}
                aria-label={`Draft by ${draft.agent}`}
                className="rounded-2xl border border-line bg-raised/60 p-3"
              >
                <p className="flex items-baseline justify-between gap-2 text-xs">
                  <span className="font-medium text-soft">{draft.agent}</span>
                  <span className="font-mono text-faint">{draft.seconds}s</span>
                </p>
                <div className="markdown mt-2 max-h-72 overflow-y-auto text-[13px] leading-relaxed">
                  <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={REHYPE}>
                    {normalizeMath(draft.answer)}
                  </ReactMarkdown>
                </div>
              </section>
            ))}
          </div>
        </details>
      )}

      {!response.complete && (
        <p className="mt-3 text-xs text-warn">This answer was cut off at the length limit.</p>
      )}

      {response.web_sources && response.web_sources.length > 0 && (
        <div className="mt-4 border-t border-line pt-3 text-xs">
          <p className="label text-muted">From the web</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {response.web_sources.map((source) => (
              <li key={source.url}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block max-w-[16rem] truncate border border-line px-2 py-1 text-cyan hover:border-cyan/60"
                >
                  {source.title}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {response.research_steps && response.research_steps.length > 0 && (
        <details className="mt-4 border-t border-line pt-3 text-xs text-soft">
          <summary className="cursor-pointer select-none text-muted hover:text-paper">
            Researched in {response.research_steps.length}{" "}
            {response.research_steps.length === 1 ? "step" : "steps"}
          </summary>
          <ResearchSteps steps={response.research_steps} />
        </details>
      )}

      {response.search_queries && response.search_queries.length > 1 && (
        <details className="mt-4 border-t border-line pt-3 text-xs text-soft">
          <summary className="cursor-pointer select-none text-muted hover:text-paper">
            Searched your sources {response.search_queries.length} ways
          </summary>
          <ol aria-label="Searches" className="mt-2 list-inside list-decimal space-y-1">
            {response.search_queries.map((query) => (
              <li key={query}>{query}</li>
            ))}
          </ol>
        </details>
      )}

      {response.chunks.length > 0 && (
        <details className="mt-4 border-t border-line pt-3 text-xs text-soft">
          <summary className="cursor-pointer select-none text-muted hover:text-paper">
            <span className="font-medium text-soft">Sources used</span> ·{" "}
            {response.chunks.length} code excerpts were given to {response.model}
            {response.reranking && response.reranking.judged > 0 && (
              <>
                {" "}
                · the judge scored {response.reranking.judged} of{" "}
                {response.reranking.candidates}, kept those ≥ {response.reranking.cutoff}/10
                {response.reranking.ranked && ", then ranked them together"}
              </>
            )}
          </summary>
          {response.reranking?.top_pick && (
            <p className="mt-2 text-soft">
              <span className="text-muted">Top pick: </span>
              {response.reranking.top_pick}
            </p>
          )}
          {response.timings && Object.keys(response.timings).length > 0 && (
            <p className="mt-2 font-mono text-faint">
              {Object.entries(response.timings)
                .map(([stage, seconds]) => `${stage} ${seconds.toFixed(1)} s`)
                .join(" · ")}
            </p>
          )}
          <ul className="mt-2 space-y-3">
            {sourcesInOrder(response).map(({ chunk, cited }) => (
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
                  className="text-left hover:text-cyan"
                >
                  <span className="font-mono">
                    {chunk.file}:{chunk.start_line}-{chunk.snippet_end_line}
                  </span>{" "}
                  <span className="text-muted">
                    {chunk.kind} {chunk.name} · {chunk.score.toFixed(2)}
                  </span>
                  {chunk.weight ? (
                    <span className="ml-1 rounded-full bg-signal/10 px-1.5 text-signal">
                      {WEIGHT_NAMES[chunk.weight]} · {chunk.weight}
                    </span>
                  ) : null}
                  {chunk.relevance !== undefined && chunk.relevance !== null && (
                    <span
                      className="ml-1 rounded-full bg-acid/10 px-1.5 text-acid"
                      title={chunk.relevance_reason ?? undefined}
                    >
                      relevance {chunk.relevance}/10
                    </span>
                  )}
                  {chunk.relevance_reason && (
                    <span className="block pl-4 text-faint">{chunk.relevance_reason}</span>
                  )}
                </button>
                <span className="ml-2 inline-flex items-center gap-2 align-middle">
                  {cited && <span className="rounded-full bg-cyan/10 px-1.5 text-cyan">cited</span>}
                  <CopyCitation chunk={chunk} />
                </span>
                <pre className="mt-1 max-h-16 overflow-hidden whitespace-pre-wrap rounded-lg bg-raised px-2 py-1 font-mono text-[11px] leading-snug text-soft">
                  {chunk.snippet.split("\n").slice(0, 3).join("\n")}
                </pre>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

/**
 * The fact-checker's report, or, for an answer citing the sources, a button to ask for one.
 * A strict answer asks for its check by itself, once shown.
 */
function FactCheckPanel({
  response,
  onChecked,
}: {
  response: AskResponse;
  onChecked?: (report: FactCheck) => void;
}) {
  const [report, setReport] = useState<FactCheck | null>(response.fact_check ?? null);
  const [state, setState] = useState<"idle" | "checking" | "failed">("idle");
  const started = useRef(false);

  const check = useCallback(() => {
    setState("checking");
    factCheck(response.question, response.answer, response.chunks)
      .then((result) => {
        setReport(result);
        setState("idle");
        onChecked?.(result);
      })
      .catch(() => setState("failed"));
  }, [response, onChecked]);

  useEffect(() => {
    if (
      response.fact_check_pending &&
      !response.fact_check &&
      !response.challenge_pending &&
      !started.current
    ) {
      started.current = true;
      check();
    }
  }, [response, check]);

  if (!report) {
    if (response.citations.length === 0 || response.chunks.length === 0) return null;
    return (
      <div className="mt-3 flex items-center gap-3 text-xs">
        <button
          type="button"
          disabled={state === "checking"}
          onClick={check}
          className="rounded-full border border-line px-3 py-1 text-cyan transition-colors hover:border-cyan/60 disabled:animate-pulse disabled:opacity-60"
        >
          {state === "checking"
            ? "Fact-checking the answer against its sources…"
            : "✓ Fact-check against the sources"}
        </button>
        {state === "failed" && (
          <span className="text-warn">The fact-checker is busy; try again in a minute.</span>
        )}
      </div>
    );
  }
  const problems = [...report.unsupported, ...report.citation_errors].length;
  return (
    <section
      aria-label="Fact-check"
      className={`mt-4 rounded-2xl border p-3 text-sm ${
        report.faithful ? "border-acid/40 bg-acid/5" : "border-warn/50 bg-warn/5"
      }`}
    >
      <p className="flex flex-wrap items-baseline gap-2">
        <span className={`font-medium ${report.faithful ? "text-acid" : "text-warn"}`}>
          {report.faithful ? "✓ Faithful to the sources" : `⚠ ${problems || "Some"} problems found`}
        </span>
        {report.verdict && <span className="text-soft">{report.verdict}</span>}
      </p>
      {report.unsupported.length > 0 && (
        <div className="mt-2">
          <p className="label text-muted">Not supported by a cited passage</p>
          <ul aria-label="Unsupported sentences" className="mt-1 list-inside list-disc space-y-1 text-soft">
            {report.unsupported.map((sentence) => (
              <li key={sentence}>{sentence}</li>
            ))}
          </ul>
        </div>
      )}
      {report.citation_errors.length > 0 && (
        <div className="mt-2">
          <p className="label text-muted">Citation errors</p>
          <ul aria-label="Citation errors" className="mt-1 list-inside list-disc space-y-1 text-soft">
            {report.citation_errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        </div>
      )}
      {report.checked_by && <p className="mt-2 text-xs text-faint">Checked by {report.checked_by}</p>}
    </section>
  );
}

const TOOL_MARK: Record<ResearchStep["tool"], string> = { search: "⌕", read: "▤", note: "✎" };

/** Deep research's tool calls, in order. */
export function ResearchSteps({ steps }: { steps: ResearchStep[] }) {
  return (
    <ol aria-label="Research steps" className="mt-2 space-y-1 text-xs text-soft">
      {steps.map((step) => (
        <li key={step.step} className="flex gap-2">
          <span aria-hidden="true" className="w-4 text-signal">
            {TOOL_MARK[step.tool]}
          </span>
          <span className="font-medium text-paper">{step.tool}</span>
          <span className="min-w-0 flex-1 truncate font-mono" title={step.input}>
            {step.input}
          </span>
          <span className="text-faint">{step.result}</span>
        </li>
      ))}
    </ol>
  );
}

const STATE: Record<EpistemicState, { label: string; hint: string; tone: string }> = {
  known: {
    label: "Known",
    hint: "Your sources answer this directly.",
    tone: "border-acid/40 bg-acid/10 text-acid",
  },
  inferred: {
    label: "Inferred",
    hint: "Your sources strongly imply this, but do not state it.",
    tone: "border-cyan/40 bg-cyan/10 text-cyan",
  },
  partial: {
    label: "Partial",
    hint: "Your sources answer part of this; what is missing is named.",
    tone: "border-warn/40 bg-warn/10 text-warn",
  },
  absent: {
    label: "Not in your sources",
    hint: "Your sources do not contain this, so it is not answered: see what is missing.",
    tone: "border-danger/40 bg-danger/10 text-danger",
  },
  conflicted: {
    label: "Conflicted",
    hint: "Your sources disagree; both sides are shown, and which is newer.",
    tone: "border-warn/50 bg-warn/15 text-warn",
  },
  general: {
    label: "General knowledge",
    hint: "Not from your sources: the model's own knowledge.",
    tone: "border-line bg-raised/60 text-muted",
  },
  web: {
    label: "From the web",
    hint: "Not from your sources: today's web results, linked.",
    tone: "border-cyan/30 bg-cyan/5 text-cyan",
  },
};

/** Where the answer stands: known, inferred, partial, absent, conflicted, or not from the
 * sources at all. Never blurred. */
function EpistemicBadge({ state }: { state: EpistemicState }) {
  const { label, hint, tone } = STATE[state];
  return (
    <span
      role="note"
      aria-label={`Epistemic state: ${label}. ${hint}`}
      title={hint}
      className={`label inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 ${tone}`}
    >
      <span aria-hidden="true">◆</span>
      {label}
    </span>
  );
}

const WEIGHT_NAMES: Record<number, string> = { 3: "primary", 2: "secondary", 1: "derived" };

const LEVEL: Record<Confidence["level"], { label: string; tone: string }> = {
  high: { label: "High confidence", tone: "border-acid/40 bg-acid/10 text-acid" },
  medium: { label: "Medium confidence", tone: "border-warn/40 bg-warn/10 text-warn" },
  low: { label: "Low confidence", tone: "border-danger/40 bg-danger/10 text-danger" },
};

/** High, medium or low: from the excerpts' relevance and how much is cited and checked. */
function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const { label, tone } = LEVEL[confidence.level];
  return (
    <span
      role="note"
      aria-label={`${label}: ${confidence.reason}`}
      title={confidence.reason}
      className={`rounded-full border px-2 py-0.5 font-medium ${tone}`}
    >
      ● {label}
    </span>
  );
}

/** The excerpts given to the model, those the answer cites first. */
function sourcesInOrder(response: AskResponse): { chunk: CodeChunk; cited: boolean }[] {
  const cites = (chunk: CodeChunk) =>
    response.citations.some(
      (c) =>
        c.file === chunk.file &&
        c.start_line <= chunk.snippet_end_line &&
        c.end_line >= chunk.start_line,
    );
  const rows = response.chunks.map((chunk) => ({ chunk, cited: cites(chunk) }));
  return [...rows.filter((r) => r.cited), ...rows.filter((r) => !r.cited)];
}

/** Copies an excerpt's citation, [path:start-end], to paste elsewhere. */
function CopyCitation({ chunk }: { chunk: CodeChunk }) {
  const [copied, setCopied] = useState(false);
  const citation = `[${chunk.file}:${chunk.start_line}-${chunk.snippet_end_line}]`;
  return (
    <button
      type="button"
      aria-label={`Copy the citation of ${chunk.name}`}
      title={citation}
      onClick={() =>
        void copyText(citation).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        })
      }
      className="rounded-full border border-line px-1.5 text-muted hover:border-cyan/60 hover:text-cyan"
    >
      {copied ? "Copied" : "⧉ Copy citation"}
    </button>
  );
}

/**
 * The self-challenge: asked for by itself once an answer from the sources is shown; the
 * final answer replaces this one, and the objection and decision fold into a note.
 */
function ChallengePanel({
  response,
  onDone,
}: {
  response: AskResponse;
  onDone?: (result: AskResponse) => void;
}) {
  const [report, setReport] = useState<SelfChallenge | null>(response.challenge ?? null);
  const [state, setState] = useState<"idle" | "challenging" | "failed">("idle");
  const started = useRef(false);

  useEffect(() => {
    if (!response.challenge_pending || response.challenge || started.current) return;
    started.current = true;
    setState("challenging");
    challengeAnswer(response.question, response.answer, response.chunks)
      .then((result) => {
        setReport(result.challenge ?? null);
        setState("idle");
        onDone?.(result);
      })
      .catch(() => setState("failed"));
  }, [response, onDone]);

  if (state === "challenging") {
    return (
      <p role="status" className="mt-3 animate-pulse text-xs text-muted">
        Self-challenging the answer against its sources…
      </p>
    );
  }
  if (!report) return null;
  return (
    <details className="mt-4 border-t border-line pt-3 text-xs text-soft">
      <summary className="cursor-pointer select-none text-muted hover:text-paper">
        Self-challenge · {report.valid ? "the objection held: answer revised" : "the answer stands"}
      </summary>
      <div aria-label="Self-challenge" role="region" className="mt-2 space-y-2">
        <p>
          <span className="label text-muted">Objection </span>
          {report.objection}
        </p>
        {!report.valid && report.reason && (
          <p>
            <span className="label text-muted">Why it does not hold </span>
            {report.reason}
          </p>
        )}
        {report.valid && report.original_answer && (
          <details>
            <summary className="cursor-pointer text-muted hover:text-paper">The answer before</summary>
            <div className="markdown mt-2 text-[13px]">
              <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={REHYPE}>
                {normalizeMath(report.original_answer)}
              </ReactMarkdown>
            </div>
          </details>
        )}
        {report.challenged_by && <p className="text-faint">Challenged by {report.challenged_by}</p>}
      </div>
    </details>
  );
}

/** The strict answer when the knowledge base has nothing on the question. */
const NOT_IN_SOURCES = "I don't have that in the knowledge base.";

/**
 * What the knowledge base lacks, when it fell short: asked for by itself after a strict
 * "not in the knowledge base" or a fact-check that found unsupported claims.
 */
function GapsPanel({
  response,
  onFound,
}: {
  response: AskResponse;
  onFound?: (gaps: GapReport) => void;
}) {
  const [gaps, setGaps] = useState<GapReport | null>(response.gaps ?? null);
  const [state, setState] = useState<"idle" | "finding" | "failed">("idle");
  const started = useRef(false);
  const short =
    response.epistemic === "absent" ||
    response.answer.trim() === NOT_IN_SOURCES ||
    (response.fact_check?.unsupported.length ?? 0) > 0;

  useEffect(() => {
    if (!short || response.gaps || started.current) return;
    started.current = true;
    setState("finding");
    findGaps(response.question)
      .then((found) => {
        setGaps(found);
        setState("idle");
        onFound?.(found);
      })
      .catch(() => setState("failed"));
  }, [short, response, onFound]);

  if (!gaps) {
    if (state === "finding") {
      return (
        <p role="status" className="mt-3 animate-pulse text-xs text-muted">
          Looking for what the knowledge base is missing…
        </p>
      );
    }
    return null;
  }
  return (
    <section aria-label="What's missing" className="mt-4 rounded-2xl border border-signal/30 bg-signal/5 p-3">
      <p className="label text-signal">What the knowledge base is missing</p>
      <div className="markdown mt-2 text-sm leading-relaxed">
        <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={REHYPE}>
          {normalizeMath(gaps.report)}
        </ReactMarkdown>
      </div>
      <p className="mt-3 flex flex-wrap items-center gap-3 text-xs">
        {gaps.suggestion_url && (
          <Link
            href={`/?add=${encodeURIComponent(gaps.suggestion_url)}`}
            className="rounded-full bg-signal px-3 py-1 font-medium text-white hover:opacity-90"
          >
            + Add this source
          </Link>
        )}
        {gaps.found_by && <span className="text-faint">Found by {gaps.found_by}</span>}
      </p>
    </section>
  );
}

/** An answer while it is being written: plain Markdown, citations not yet checked. */
export function StreamingAnswer({ text }: { text: string }) {
  return (
    <article aria-label="Writing the answer" aria-busy="true" className="slab bg-panel/80 py-4 pl-5 pr-4">
      <div className="markdown text-[15px] leading-relaxed">
        <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={REHYPE} components={{ pre: CodePre }}>
          {normalizeMath(text)}
        </ReactMarkdown>
      </div>
      <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-acid align-middle" />
    </article>
  );
}

/** Drawn pictures: one large, or several side by side. */
export function Gallery({ images }: { images: GeneratedImage[] }) {
  if (images.length === 1) {
    return (
      <div className="mt-4 max-w-md">
        <Picture image={images[0]} />
      </div>
    );
  }
  return (
    <ul aria-label="Pictures" className="mt-4 grid grid-cols-2 gap-3">
      {images.map((image, index) => (
        <li key={`${index}-${image.url.slice(0, 80)}`}>
          <Picture image={image} />
        </li>
      ))}
    </ul>
  );
}

/** A drawn picture: shown as it loads, with links to open and save it. */
function Picture({ image }: { image: GeneratedImage }) {
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  // Browsers will not open a data: URL in a new tab; such pictures can only be saved.
  const embedded = image.url.startsWith("data:");
  const extension = image.url.startsWith("data:image/webp") ? "webp" : "jpg";
  return (
    <figure>
      <div className="relative aspect-square w-full overflow-hidden border border-line bg-raised shadow-block">
        {state === "loading" && (
          <p className="label absolute inset-0 flex animate-pulse items-center justify-center text-muted">
            Drawing…
          </p>
        )}
        {state === "failed" && (
          <p className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-danger">
            The picture could not be drawn. The image service may be busy; try again.
          </p>
        )}
        {/* eslint-disable-next-line @next/next/no-img-element -- drawn elsewhere, any size */}
        <img
          src={image.url}
          alt={image.prompt}
          onLoad={() => setState("ready")}
          onError={() => setState("failed")}
          className={`h-full w-full object-cover transition-opacity ${state === "ready" ? "opacity-100" : "opacity-0"}`}
        />
      </div>
      <figcaption className="mt-2 flex flex-wrap items-center gap-3 text-xs">
        {image.service && <span className="label text-muted">{image.service}</span>}
        {!embedded && (
          <a href={image.url} target="_blank" rel="noreferrer" className="text-cyan hover:underline">
            Open full size
          </a>
        )}
        <a
          href={image.url}
          download={`atlas-picture.${extension}`}
          className="text-cyan hover:underline"
        >
          Download
        </a>
      </figcaption>
    </figure>
  );
}

interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: { className?: unknown };
  children?: HastNode[];
}

function textOf(node: HastNode | undefined): string {
  if (!node) return "";
  if (node.type === "text") return node.value ?? "";
  return (node.children ?? []).map(textOf).join("");
}

/** A fenced code block: highlighted once the language's grammar loads, with a copy button. */
function CodePre({ node, children }: { node?: unknown; children?: ReactNode }) {
  const code = (node as HastNode | undefined)?.children?.find((c) => c.tagName === "code");
  const classes = code?.properties?.className;
  const language =
    (Array.isArray(classes) ? classes : [])
      .map(String)
      .find((c) => c.startsWith("language-"))
      ?.slice("language-".length) ?? "";
  const text = textOf(code).replace(/\n$/, "");
  const [html, setHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setHtml(null);
    if (!language || text.length > 60_000) return;
    let current = true;
    // Loaded on demand, in the browser only (see CodePanel for why).
    void import("@/lib/highlight")
      .then(({ highlightSnippet }) => highlightSnippet(text, language))
      .then((result) => {
        if (current) setHtml(result);
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [text, language]);

  async function copy() {
    await copyText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="not-prose overflow-hidden border border-line bg-[#101010]">
      <div className="flex items-center justify-between border-b border-line bg-panel px-3 py-1">
        <span className="label text-muted">{language || "text"}</span>
        <button
          type="button"
          onClick={() => void copy()}
          className="label text-muted transition-colors hover:text-acid"
        >
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>
      {html ? (
        // Shiki escapes the code; the markup is its own token spans.
        <div className="[&_pre]:!m-0" dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <pre>{children}</pre>
      )}
    </div>
  );
}
