"use client";

import type { HealthReport, SymbolRef } from "@atlas/shared";
import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getHealth } from "@/lib/api";
import { useApi } from "@/lib/useApi";

import { ErrorMessage, Loading, NothingIngested } from "./States";

const INDIGO = "#6366f1";
const RED = "#dc2626";
const AMBER = "#f59e0b";
const CHART_ROWS = 12;

interface Datum {
  name: string;
  value: number;
  flagged: boolean;
}

function basename(path: string): string {
  return path.split("/").slice(-2).join("/");
}

function countBy(symbols: SymbolRef[]): Datum[] {
  const counts = new Map<string, number>();
  for (const symbol of symbols) counts.set(symbol.file, (counts.get(symbol.file) ?? 0) + 1);
  return [...counts]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, CHART_ROWS)
    .map(([file, value]) => ({ name: basename(file), value, flagged: false }));
}

export function HealthDashboard() {
  // The report proper uses the API's default thresholds. The charts need the top
  // of each ranking whether or not it crosses a threshold, hence the second call.
  const report = useApi(() => getHealth());
  const ranking = useApi(() =>
    getHealth({ max_function_loc: 1, min_fan_out: 1, limit: CHART_ROWS }),
  );

  if (report.status === "loading" || ranking.status === "loading") {
    return <Loading label="Computing code health…" />;
  }
  if (report.status === "error") return <ErrorMessage message={report.message} />;
  if (ranking.status === "error") return <ErrorMessage message={ranking.message} />;
  if (report.data.summary.files === 0) return <NothingIngested />;

  return <Dashboard report={report.data} ranking={ranking.data} />;
}

function Dashboard({ report, ranking }: { report: HealthReport; ranking: HealthReport }) {
  const { summary, thresholds, circular_dependencies: cycles } = report;
  const cycleCount = summary.file_cycles + summary.call_cycles;

  const longest: Datum[] = ranking.long_functions.map((fn) => ({
    name: fn.name,
    value: fn.loc,
    flagged: fn.loc > thresholds.max_function_loc,
  }));
  const fanOut: Datum[] = ranking.high_fan_out_files.map((file) => ({
    name: basename(file.file),
    value: file.fan_out,
    flagged: file.fan_out >= thresholds.min_fan_out,
  }));

  return (
    <main className="mx-auto w-full max-w-7xl space-y-8 px-4 py-6">
      <header>
        <h1 className="text-xl font-semibold">Code health</h1>
        <p className="mt-1 text-sm text-slate-600">
          {summary.files} files, {summary.symbols} symbols and {summary.edges} relationships
          analysed.
        </p>
      </header>

      <section aria-label="Summary" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Dead symbols" value={summary.dead_symbols} tone="amber" />
        <Stat label="Circular dependencies" value={cycleCount} tone="red" />
        <Stat
          label={`Functions over ${thresholds.max_function_loc} lines`}
          value={summary.long_functions}
          tone="amber"
        />
        <Stat
          label={`Files with fan-out ≥ ${thresholds.min_fan_out}`}
          value={summary.high_fan_out_files}
          tone="amber"
        />
      </section>

      <section aria-labelledby="complexity">
        <h2 id="complexity" className="text-base font-semibold">
          Complexity
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Measured as function length and as fan-out, the number of other files a file depends
          on. Bars past a threshold are red.
        </p>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <ChartCard title="Longest functions" unit="lines" testId="chart-longest">
            <Bars data={longest} threshold={thresholds.max_function_loc} unit="lines" />
          </ChartCard>
          <ChartCard title="Highest fan-out" unit="files depended on" testId="chart-fan-out">
            <Bars data={fanOut} threshold={thresholds.min_fan_out} unit="files" />
          </ChartCard>
        </div>
      </section>

      <section aria-labelledby="dead-code">
        <h2 id="dead-code" className="text-base font-semibold">
          Dead code
        </h2>
        <p className="mt-1 max-w-3xl text-xs text-slate-500">
          Functions and methods with no caller or import that Atlas could resolve. Treat these
          as candidates: a method reached only through a variable, or declared on an interface,
          is listed even though it is used.
        </p>
        {report.dead_symbols.length === 0 ? (
          <p className="mt-4 text-sm text-slate-600">No dead symbols found.</p>
        ) : (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <ChartCard title="Dead symbols by file" unit="symbols" testId="chart-dead">
              <Bars data={countBy(report.dead_symbols)} unit="symbols" color={AMBER} />
            </ChartCard>
            <div className="max-h-96 overflow-auto rounded-lg border border-slate-200 bg-white">
              <table className="w-full text-left text-xs">
                <caption className="sr-only">Dead symbols</caption>
                <thead className="sticky top-0 bg-slate-50 text-slate-500">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-medium">Symbol</th>
                    <th scope="col" className="px-3 py-2 font-medium">Kind</th>
                    <th scope="col" className="px-3 py-2 font-medium">Location</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {report.dead_symbols.map((symbol) => (
                    <tr key={symbol.id}>
                      <td className="break-all px-3 py-1.5 font-mono">{symbol.name}</td>
                      <td className="px-3 py-1.5 text-slate-500">{symbol.kind}</td>
                      <td className="break-all px-3 py-1.5 font-mono text-slate-500">
                        {symbol.file}:{symbol.start_line}-{symbol.end_line}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {summary.dead_symbols > report.dead_symbols.length && (
                <p className="border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
                  Showing {report.dead_symbols.length} of {summary.dead_symbols}.
                </p>
              )}
            </div>
          </div>
        )}
      </section>

      <section aria-labelledby="cycles">
        <h2 id="cycles" className="text-base font-semibold">
          Circular dependencies
        </h2>
        {cycleCount === 0 ? (
          <p className="mt-2 text-sm text-slate-600">No circular dependencies found.</p>
        ) : (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <CycleList
              title="Files that depend on each other"
              cycles={cycles.files.map((files) => files.map((file) => ({ key: file, label: file })))}
            />
            <CycleList
              title="Functions that call each other"
              cycles={cycles.calls.map((symbols) =>
                symbols.map((symbol) => ({
                  key: String(symbol.id),
                  label: `${symbol.name} (${basename(symbol.file)})`,
                })),
              )}
            />
          </div>
        )}
      </section>
    </main>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: "amber" | "red" }) {
  const color = value === 0 ? "text-emerald-600" : tone === "red" ? "text-red-600" : "text-amber-600";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`mt-1 text-3xl font-semibold tabular-nums ${color}`}>{value}</p>
    </div>
  );
}

function ChartCard({
  title,
  unit,
  testId,
  children,
}: {
  title: string;
  unit: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <figure data-testid={testId} className="rounded-lg border border-slate-200 bg-white p-4">
      <figcaption className="text-sm font-medium">
        {title} <span className="font-normal text-slate-400">({unit})</span>
      </figcaption>
      <div className="mt-3 h-80">{children}</div>
    </figure>
  );
}

function Bars({
  data,
  unit,
  threshold,
  color = INDIGO,
}: {
  data: Datum[];
  unit: string;
  threshold?: number;
  color?: string;
}) {
  if (data.length === 0) {
    return <p className="pt-8 text-center text-sm text-slate-500">Nothing to show.</p>;
  }
  const peak = Math.max(...data.map((d) => d.value));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
        <CartesianGrid horizontal={false} stroke="#e2e8f0" />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
        <YAxis
          type="category"
          dataKey="name"
          width={170}
          interval={0}
          tick={{ fontSize: 11 }}
          tickFormatter={(name: string) => (name.length > 26 ? `…${name.slice(-25)}` : name)}
        />
        <Tooltip formatter={(value) => [`${String(value)} ${unit}`, ""]} separator="" />
        {threshold !== undefined && threshold <= peak && (
          <ReferenceLine x={threshold} stroke={RED} strokeDasharray="4 3" />
        )}
        <Bar dataKey="value" isAnimationActive={false} radius={[0, 3, 3, 0]}>
          {data.map((datum) => (
            <Cell key={datum.name} fill={datum.flagged ? RED : color} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function CycleList({
  title,
  cycles,
}: {
  title: string;
  cycles: { key: string; label: string }[][];
}) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-4">
      <h3 className="text-sm font-medium text-red-900">
        {title} <span className="font-normal">({cycles.length})</span>
      </h3>
      {cycles.length === 0 ? (
        <p className="mt-2 text-xs text-red-800">None.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {cycles.map((cycle) => (
            <li key={cycle.map((member) => member.key).join("|")} className="text-xs text-red-900">
              <span className="font-mono">{cycle.map((member) => member.label).join(" ⇄ ")}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
