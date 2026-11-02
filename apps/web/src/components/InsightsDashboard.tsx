"use client";

import type { AnalyticsMetric, AnalyticsResult } from "@atlas/shared";
import Link from "next/link";
import { useState } from "react";

import { exportAnalytics, exportAnswers, getAnalytics } from "@/lib/api";
import { useApi } from "@/lib/useApi";

import { Loading } from "./States";

/** What each surface is for, as the dashboard says it. */
const SURFACES: { metric: AnalyticsMetric; title: string; hint: string }[] = [
  { metric: "top_questions", title: "Top questions", hint: "Asked most: candidates to cache or document better." },
  { metric: "failing", title: "Failing questions", hint: "Thumbs down or unchecked citations: candidates to fix." },
  { metric: "gaps", title: "Top gaps", hint: "Answered partly or not at all: candidates to ingest." },
  { metric: "slowest", title: "Slowest", hint: "Candidates to optimise." },
  { metric: "sources", title: "Sources by usage", hint: "Retrieved and cited: candidates to prune or promote." },
  { metric: "feedback", title: "Feedback", hint: "The thumbs, with their reasons." },
];

async function loadAll(window: number): Promise<Record<string, AnalyticsResult>> {
  const metrics: AnalyticsMetric[] = [...SURFACES.map((s) => s.metric), "drift"];
  const results = await Promise.all(metrics.map((m) => getAnalytics(m, m === "drift" ? Math.max(window, 28) : window)));
  return Object.fromEntries(results.map((r) => [r.metric, r]));
}

function save(blob: Blob, name: string) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
}

/** Analytics over the answer log, with export. Admin only. */
export function InsightsDashboard() {
  const [window, setWindow] = useState(7);
  const data = useApi(() => loadAll(window), String(window));

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-4xl font-semibold">Insights</h1>
          <p className="mt-1 text-sm text-soft">What people ask, what fails, what is missing and how it is trending.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label className="flex items-center gap-2 text-muted">
            Window
            <select
              value={window}
              onChange={(event) => setWindow(Number(event.target.value))}
              className="rounded-full border border-line bg-raised px-2 py-1 text-soft"
            >
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => void exportAnswers().then((blob) => save(blob, "atlas-qa.jsonl"))}
            className="rounded-full border border-line px-3 py-1 text-cyan hover:border-cyan/60"
          >
            Answers as JSONL
          </button>
        </div>
      </div>

      {data.status === "loading" && <Loading label="Reading the answer log…" />}
      {data.status === "error" && (
        <p role="alert" className="mt-6 text-sm text-danger">
          {/401|admin/i.test(data.message) ? (
            <>
              Insights need the admin password: unlock it on the{" "}
              <Link href="/" className="underline">
                Sources page
              </Link>
              .
            </>
          ) : (
            data.message
          )}
        </p>
      )}
      {data.status === "ready" && (
        <>
          <Drift result={data.data.drift} />
          <div className="mt-6 grid gap-4 lg:grid-cols-2">
            {SURFACES.map((surface) => (
              <Surface key={surface.metric} {...surface} result={data.data[surface.metric]} window={window} />
            ))}
          </div>
        </>
      )}
    </main>
  );
}

function cell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}

function Surface({
  metric,
  title,
  hint,
  result,
  window,
}: {
  metric: AnalyticsMetric;
  title: string;
  hint: string;
  result: AnalyticsResult;
  window: number;
}) {
  const rows = result.rows;
  const columns = rows.length ? Object.keys(rows[0]).filter((k) => k !== "at") : [];
  return (
    <section aria-labelledby={`insight-${metric}`} className="glass rounded-glass p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 id={`insight-${metric}`} className="font-semibold text-paper">
            {title}
          </h2>
          <p className="text-xs text-muted">{hint}</p>
        </div>
        <button
          type="button"
          aria-label={`${title} as CSV`}
          onClick={() => void exportAnalytics(metric, window).then((blob) => save(blob, `atlas-${metric}.csv`))}
          className="shrink-0 rounded-full border border-line px-2 py-0.5 text-xs text-cyan"
        >
          CSV
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="mt-3 text-xs text-faint">Nothing in the last {result.window} days.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-muted">
              <tr>
                {columns.map((c) => (
                  <th key={c} scope="col" className="pb-1 pr-3 font-normal">
                    {c.replace(/_/g, " ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="text-soft">
              {rows.map((row, i) => (
                <tr key={i} className="border-t border-line align-top">
                  {columns.map((c) => (
                    <td key={c} className={`py-1 pr-3 ${typeof row[c] === "number" ? "text-right tabular-nums" : ""}`}>
                      {c === "suggestion" && typeof row[c] === "string" ? (
                        <a href={`${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/?add=${encodeURIComponent(row[c] as string)}`} className="text-cyan underline">
                          + add
                        </a>
                      ) : (
                        cell(row[c])
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const DRIFT = [
  { key: "hit_rate", label: "Hit rate", better: 1 },
  { key: "faithfulness", label: "Faithfulness", better: 1 },
  { key: "approval", label: "Approval", better: 1 },
  { key: "latency_ms", label: "Latency (ms)", better: -1 },
] as const;

/** Week over week: the latest value of each, and its change, worded and coloured. */
function Drift({ result }: { result: AnalyticsResult }) {
  const weeks = result.rows;
  const latest = weeks.at(-1) as Record<string, unknown> | undefined;
  const change = (latest?.change ?? {}) as Record<string, number>;
  return (
    <section aria-labelledby="insight-drift" className="glass mt-6 rounded-glass p-4">
      <h2 id="insight-drift" className="font-semibold text-paper">
        Drift, week over week
      </h2>
      {!latest ? (
        <p className="mt-2 text-xs text-faint">No answers logged yet.</p>
      ) : (
        <dl className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {DRIFT.map(({ key, label, better }) => {
            const delta = change[key];
            const good = delta === undefined || delta === 0 ? null : delta * better > 0;
            return (
              <div key={key}>
                <dt className="text-xs text-muted">{label}</dt>
                <dd className="font-display text-2xl text-paper">{cell(latest[key])}</dd>
                {delta !== undefined && (
                  <dd className={`text-xs ${good === null ? "text-muted" : good ? "text-ok" : "text-danger"}`}>
                    {delta === 0 ? "unchanged" : `${delta > 0 ? "▲" : "▼"} ${Math.abs(delta)} ${good ? "better" : "worse"}`}
                  </dd>
                )}
              </div>
            );
          })}
        </dl>
      )}
      <p className="mt-2 text-xs text-faint">
        {weeks.length} week(s) · latest {cell(latest?.week)} · {cell(latest?.answers)} answers
      </p>
    </section>
  );
}
