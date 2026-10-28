"use client";

import type { CodeAnalysis, CodeFinding, Severity } from "@atlas/shared";
import { useMemo, useState } from "react";

const SEVERITIES: Severity[] = ["high", "medium", "low"];

const SEVERITY_TONE: Record<Severity, string> = {
  high: "border-danger/60 bg-danger/10 text-danger",
  medium: "border-warn/60 bg-warn/10 text-warn",
  low: "border-line text-muted",
};

function gradeTone(grade: string): string {
  if (grade === "A") return "bg-ok text-ink";
  if (grade === "B") return "bg-acid text-ink";
  if (grade === "C") return "bg-warn text-ink";
  return "bg-danger text-paper";
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className="label text-muted">{title}</h3>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function Findings({ findings, total }: { findings: CodeFinding[]; total: number }) {
  const [shown, setShown] = useState<Severity | "all">("all");
  const [all, setAll] = useState(false);
  const picked = useMemo(
    () => (shown === "all" ? findings : findings.filter((f) => f.severity === shown)),
    [findings, shown],
  );
  const visible = all ? picked : picked.slice(0, 40);
  return (
    <>
      <div role="group" aria-label="Show findings" className="flex flex-wrap gap-1.5">
        {(["all", ...SEVERITIES] as const).map((level) => (
          <button
            key={level}
            type="button"
            aria-pressed={shown === level}
            onClick={() => setShown(level)}
            className={`border px-2 py-0.5 font-mono text-[10.5px] uppercase tracking-[0.12em] ${
              shown === level ? "border-signal text-paper" : "border-line text-muted hover:text-paper"
            }`}
          >
            {level}
          </button>
        ))}
      </div>
      {visible.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No findings at this level.</p>
      ) : (
        <ul aria-label="Findings" className="mt-2 divide-y divide-line border border-line">
          {visible.map((f, index) => (
            <li key={`${f.path}:${f.line}:${f.rule}:${index}`} className="flex gap-3 px-3 py-2 text-sm">
              <span
                className={`h-fit shrink-0 border px-1.5 font-mono text-[10px] uppercase ${SEVERITY_TONE[f.severity]}`}
              >
                {f.severity}
              </span>
              <span className="min-w-0">
                <span className="font-mono text-[12px] text-cyan">
                  {f.path}:{f.line}
                </span>{" "}
                <span className="font-mono text-[11px] text-faint">
                  {f.tool} {f.rule}
                </span>
                <span className="block text-soft">{f.message}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {!all && picked.length > visible.length && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="mt-2 font-mono text-[11px] uppercase tracking-[0.12em] text-cyan hover:underline"
        >
          Show all {picked.length}
        </button>
      )}
      {total > findings.length && (
        <p className="mt-1 text-xs text-faint">
          The first {findings.length} of {total} findings are listed.
        </p>
      )}
    </>
  );
}

/** What the code analyser found: a score, the riskiest code, and every finding. */
export function AnalysisReport({ analysis }: { analysis: CodeAnalysis }) {
  const total = analysis.counts.high + analysis.counts.medium + analysis.counts.low;
  const languages = Object.entries(analysis.languages)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  const biggest = languages[0]?.[1] ?? 1;

  return (
    <div aria-label="Code analysis" role="region">
      <div className="flex flex-wrap items-center gap-4">
        <span
          aria-label={`Grade ${analysis.grade}`}
          className={`flex h-14 w-14 items-center justify-center font-display text-3xl font-extrabold ${gradeTone(analysis.grade)}`}
        >
          {analysis.grade}
        </span>
        <div>
          <p className="font-display text-xl font-bold">
            {analysis.score}
            <span className="text-sm text-muted">/100</span>
          </p>
          <p className="text-xs text-muted">
            {analysis.files} files · {analysis.code_lines.toLocaleString()} lines of code
            {analysis.test_files != null && ` · ${analysis.test_files} test files`}
            {analysis.seconds != null && ` · analysed in ${analysis.seconds}s`}
          </p>
          {analysis.repo && (
            <p className="text-xs text-faint">
              <a href={analysis.repo} target="_blank" rel="noreferrer" className="text-cyan hover:underline">
                {analysis.repo.replace("https://github.com/", "")}
              </a>
              {analysis.commit && ` @ ${analysis.commit.slice(0, 10)}`}
            </p>
          )}
        </div>
        <ul aria-label="Findings by severity" className="ml-auto flex gap-1.5">
          {SEVERITIES.map((level) => (
            <li key={level} className={`border px-2 py-1 font-mono text-[11px] ${SEVERITY_TONE[level]}`}>
              {analysis.counts[level]} {level}
            </li>
          ))}
        </ul>
      </div>

      {languages.length > 0 && (
        <ul aria-label="Languages" className="mt-4 space-y-1">
          {languages.map(([language, lines]) => (
            <li key={language} className="flex items-center gap-2 font-mono text-[11px] text-muted">
              <span className="w-20 shrink-0 truncate">{language}</span>
              <span className="h-1.5 bg-signal/70" style={{ width: `${Math.max(2, (lines / biggest) * 60)}%` }} />
              <span>{lines.toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}

      {analysis.riskiest && analysis.riskiest.length > 0 && (
        <Section title="Riskiest files">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-left text-sm">
              <thead className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-faint">
                <tr>
                  <th className="py-1 pr-3 font-normal">File</th>
                  <th className="py-1 pr-3 font-normal">Findings</th>
                  <th className="py-1 pr-3 font-normal">Worst complexity</th>
                  <th className="py-1 pr-3 font-normal">Imported by</th>
                </tr>
              </thead>
              <tbody>
                {analysis.riskiest.map((file) => (
                  <tr key={file.path} className="border-t border-line">
                    <td className="py-1.5 pr-3 font-mono text-[12px] text-cyan">{file.path}</td>
                    <td className="py-1.5 pr-3">{file.findings}</td>
                    <td className="py-1.5 pr-3">{file.complexity}</td>
                    <td className="py-1.5 pr-3">{file.imported_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {analysis.cycles && analysis.cycles.length > 0 && (
        <Section title="Import cycles">
          <ul className="space-y-1 font-mono text-[12px] text-warn">
            {analysis.cycles.map((cycle) => (
              <li key={cycle.join(">")}>{cycle.join(" ↔ ")}</li>
            ))}
          </ul>
        </Section>
      )}

      {analysis.functions.length > 0 && (
        <Section title="Most complex functions">
          <ul className="space-y-1 text-sm">
            {analysis.functions.slice(0, 10).map((fn) => (
              <li key={`${fn.path}:${fn.start_line}:${fn.name}`} className="flex flex-wrap gap-x-3">
                <span className="font-mono text-[12px] text-cyan">
                  {fn.path}:{fn.start_line}-{fn.end_line}
                </span>
                <span>{fn.name}</span>
                <span className="font-mono text-[11px] text-muted">
                  complexity {fn.complexity} · nesting {fn.nesting}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title={`Findings (${total})`}>
        <Findings findings={analysis.findings} total={total} />
      </Section>
    </div>
  );
}
