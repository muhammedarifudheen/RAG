"use client";

import type { IngestPreview, SourceHealth, SourceHealthAction, SourceHealthReport } from "@atlas/shared";
import { useState } from "react";

import {
  deleteSource,
  getSourceHealth,
  previewSource,
  primaryCandidates,
  setSourceWeight,
} from "@/lib/api";
import { useApi } from "@/lib/useApi";

/** The knowledge base's live health: one score with its history, and each source's
 * metrics with an action for each problem. */
export function SourceHealthPanel() {
  const [revision, setRevision] = useState(0);
  const report = useApi(getSourceHealth, String(revision));
  if (report.status !== "ready" || report.data.sources.length === 0) return null;
  return (
    <section aria-labelledby="source-health-heading" className="mx-auto mt-6 w-full max-w-6xl px-4">
      <Overview report={report.data} />
      <ul aria-label="Source health" className="mt-4 grid gap-3 md:grid-cols-2">
        {report.data.sources.map((source) => (
          <SourceCard key={source.id} source={source} onChanged={() => setRevision((v) => v + 1)} />
        ))}
      </ul>
    </section>
  );
}

function tone(score: number): string {
  if (score >= 75) return "text-ok";
  if (score >= 50) return "text-warn";
  return "text-danger";
}

function Overview({ report }: { report: SourceHealthReport }) {
  return (
    <div className="glass flex flex-wrap items-center gap-6 rounded-glass p-5">
      <div>
        <h2 id="source-health-heading" className="label text-muted">
          Knowledge base health
        </h2>
        <p className="mt-1 flex items-baseline gap-2">
          <span aria-label={`Overall health score ${report.score} of 100`} className={`font-display text-5xl font-semibold ${tone(report.score)}`}>
            {report.score}
          </span>
          <span className="text-sm text-muted">/ 100 · {report.sources.length} sources · {report.answers} answers in 30 days</span>
        </p>
      </div>
      <Sparkline points={report.history.map((h) => h.score)} />
    </div>
  );
}

/** The score over time. */
function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) {
    return <p className="text-xs text-faint">The score&apos;s history starts now; it is kept every six hours.</p>;
  }
  const width = 220;
  const height = 48;
  const step = width / (points.length - 1);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)} ${(height - (p / 100) * height).toFixed(1)}`).join(" ");
  const last = points.at(-1) ?? 0;
  const change = last - (points.at(-2) ?? last);
  const takeaway =
    change === 0 ? "Unchanged since the last check" : `${change > 0 ? "▲ Up" : "▼ Down"} ${Math.abs(change)} since the last check`;
  return (
    <div className="flex items-center gap-3">
      <svg
        role="img"
        aria-label={`Health score over the last ${points.length} checks, on a 0 to 100 scale: from ${points[0]} to ${last}. ${takeaway}.`}
        viewBox={`0 0 ${width} ${height}`}
        className="h-12 w-56"
      >
        <path d={path} fill="none" stroke="rgb(var(--signal))" strokeWidth="2" strokeLinejoin="round" />
        <circle cx={width} cy={height - (last / 100) * height} r="3" fill="rgb(var(--signal))" />
      </svg>
      <span aria-hidden="true" className={`text-xs ${change < 0 ? "text-danger" : change > 0 ? "text-ok" : "text-muted"}`}>
        {takeaway}
      </span>
    </div>
  );
}

function percent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function SourceCard({ source, onChanged }: { source: SourceHealth; onChanged: () => void }) {
  const { freshness, retrieval, trust } = source;
  return (
    <li className="glass rounded-glass p-4 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium text-paper">{source.title}</p>
          <p className="text-xs text-muted">
            {source.kind} · version {source.version}
          </p>
        </div>
        <span aria-label={`Score ${source.score}`} className={`font-display text-2xl font-semibold ${tone(source.score)}`}>
          {source.score}
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
        <Metric name="Coverage" value={percent(source.coverage)} />
        <Metric
          name="Freshness"
          value={`${freshness.label ?? "unknown"}${freshness.age_days !== null ? ` · ${freshness.age_days}d` : ""} · ${freshness.trend}`}
        />
        <Metric name="Redundancy" value={percent(source.redundancy)} />
        <Metric name="Trust" value={`${trust.label} (${trust.weight})`} title={trust.evidence} />
        <Metric name="Precision" value={`${percent(retrieval.precision)} of ${retrieval.retrieved}`} />
        <Metric name="Relevance" value={retrieval.mean_relevance === null ? "—" : `${retrieval.mean_relevance}/10`} />
      </dl>
      {source.staleness_risk > 0 && (
        <p className="mt-2 text-xs text-warn">{source.staleness_risk} answer(s) found it outdated beside a newer source.</p>
      )}
      {source.gaps.length > 0 && (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer text-muted">Gaps: {source.gaps.length} question(s) it could not answer</summary>
          <ul className="mt-1 list-disc pl-5 text-soft">
            {source.gaps.map((gap) => (
              <li key={gap.question}>{gap.question}</li>
            ))}
          </ul>
        </details>
      )}
      {source.actions.length > 0 && (
        <ul aria-label={`Actions for ${source.title}`} className="mt-3 space-y-2">
          {source.actions.map((action) => (
            <Action key={action.kind} source={source} action={action} onChanged={onChanged} />
          ))}
        </ul>
      )}
    </li>
  );
}

function Metric({ name, value, title }: { name: string; value: string; title?: string }) {
  return (
    <div title={title}>
      <dt className="text-faint">{name}</dt>
      <dd className="text-soft">{value}</dd>
    </div>
  );
}

const ADD = (url: string) => `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/?add=${encodeURIComponent(url)}`;

function Action({ source, action, onChanged }: { source: SourceHealth; action: SourceHealthAction; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [diff, setDiff] = useState<IngestPreview | null>(null);
  const [links, setLinks] = useState<string[] | null>(action.candidates ?? null);

  async function run(job: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await job();
    } catch (failure) {
      const message = failure instanceof Error ? failure.message : "That did not work.";
      setError(/admin/i.test(message) ? `${message} Unlock admin on the Sources page.` : message);
    } finally {
      setBusy(false);
    }
  }

  const button = (label: string, job: () => Promise<void>) => (
    <button
      type="button"
      disabled={busy}
      onClick={() => void run(job)}
      className="rounded-full border border-signal/50 px-3 py-0.5 text-xs text-signal hover:bg-signal/10 disabled:opacity-50"
    >
      {busy ? "Working…" : label}
    </button>
  );

  return (
    <li className="rounded-lg border border-line bg-raised/40 p-2">
      <p className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-paper">{action.label}</span>
        <span className="text-muted">{action.detail}</span>
      </p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        {action.kind === "reingest" &&
          (diff ? (
            source.url && (
              <a href={ADD(source.url)} className="rounded-full bg-signal px-3 py-0.5 text-xs text-on-signal">
                Re-ingest now
              </a>
            )
          ) : (
            button("Preview changes", async () => setDiff(await previewSource(source.id)))
          ))}
        {action.kind === "demote" && button("Demote", async () => {
          await setSourceWeight(source.id, 1);
          onChanged();
        })}
        {action.kind === "merge" && button("Remove this copy", async () => {
          if (!window.confirm(`Remove ${source.title}? Its passages are kept in the other sources.`)) return;
          await deleteSource(source.id);
          onChanged();
        })}
        {action.kind === "primary" && !links && button("Find primary sources", async () => setLinks(await primaryCandidates(source.id)))}
        {(action.kind === "primary" || action.kind === "gap") &&
          links?.map((url) => (
            <a key={url} href={ADD(url)} title="Add this source" className="max-w-full truncate rounded-full border border-line px-2 py-0.5 text-xs text-cyan hover:border-cyan/60">
              + {url}
            </a>
          ))}
      </div>
      {diff && (
        <p aria-label="Re-ingest preview" className="mt-1.5 text-xs text-soft">
          {diff.added.length} added · {diff.changed.length} changed · {diff.removed.length} removed · {diff.unchanged} unchanged
          {diff.changed.length > 0 && <span className="block truncate text-muted">Changed: {diff.changed.slice(0, 5).join(", ")}</span>}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {error}
        </p>
      )}
    </li>
  );
}
