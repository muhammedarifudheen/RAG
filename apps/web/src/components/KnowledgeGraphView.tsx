"use client";

import type { KgEdge, KgGraph, KgNode, KgNodeDetail } from "@atlas/shared";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { useMemo, useState, type FormEvent } from "react";

import { askGraph, getKgNode, getKnowledgeGraph } from "@/lib/api";
import { useApi } from "@/lib/useApi";

import { ErrorMessage, Loading } from "./States";

/** How each kind of node is drawn: a shape and a colour, so neither alone carries it. */
const LOOKS: Record<string, { shape: "circle" | "square" | "diamond" | "triangle" | "hexagon"; color: string; label: string }> = {
  code: { shape: "circle", color: "#33d6f0", label: "Code" },
  section: { shape: "circle", color: "#8b6cff", label: "Passage" },
  file: { shape: "square", color: "#7f8cff", label: "File" },
  source: { shape: "hexagon", color: "#ffc44d", label: "Source" },
  concept: { shape: "square", color: "#2ee59d", label: "Concept" },
  entity: { shape: "diamond", color: "#ff4fb3", label: "Entity" },
  person: { shape: "triangle", color: "#ff7a3d", label: "Person" },
};

function look(type: string) {
  if (["function", "method", "class", "module"].includes(type)) return LOOKS.code;
  return LOOKS[type] ?? LOOKS.code;
}

const EDGE_COLOR: Partial<Record<KgEdge["kind"], string>> = {
  contradicts: "#ff6070",
  supersedes: "#ffc44d",
  derived_from: "#a0a4c0",
  references: "#2ee59d",
  example_of: "#2ee59d",
  mentioned_in: "#8b6cff",
};

interface Placed extends SimulationNodeDatum {
  id: string;
  node: KgNode;
}

/** Lays the graph out by force: linked nodes pull together, every node is drawn toward
 * its source's place on a ring, so each source forms a cluster. */
function layout(graph: KgGraph): { nodes: Placed[]; width: number; height: number; minX: number; minY: number } {
  const sources = [...new Set(graph.nodes.map((n) => n.source_id ?? -1))];
  const radius = 120 + sources.length * 40;
  const centre = new Map(
    sources.map((id, i) => {
      const angle = (2 * Math.PI * i) / Math.max(sources.length, 1);
      return [id, { x: id === -1 ? 0 : Math.cos(angle) * radius, y: id === -1 ? 0 : Math.sin(angle) * radius }];
    }),
  );
  const nodes: Placed[] = graph.nodes.map((node) => ({ id: node.id, node }));
  const links: SimulationLinkDatum<Placed>[] = graph.edges.map((e) => ({ source: e.source, target: e.target }));
  forceSimulation(nodes)
    .force("link", forceLink<Placed, SimulationLinkDatum<Placed>>(links).id((n) => n.id).distance(50).strength(0.4))
    .force("charge", forceManyBody().strength(-90))
    .force("collide", forceCollide(14))
    .force("x", forceX<Placed>((n) => centre.get(n.node.source_id ?? -1)!.x).strength(0.12))
    .force("y", forceY<Placed>((n) => centre.get(n.node.source_id ?? -1)!.y).strength(0.12))
    .stop()
    .tick(300);
  const xs = nodes.map((n) => n.x ?? 0);
  const ys = nodes.map((n) => n.y ?? 0);
  const pad = 40;
  const minX = Math.min(...xs, 0) - pad;
  const minY = Math.min(...ys, 0) - pad;
  return { nodes, minX, minY, width: Math.max(...xs, 0) - minX + pad, height: Math.max(...ys, 0) - minY + pad };
}

function Shape({ shape, color, size, selected }: { shape: string; color: string; size: number; selected: boolean }) {
  // Outlined in the theme's text colour, so every mark stands out in light and dark.
  const common = {
    fill: color,
    fillOpacity: 0.85,
    style: { stroke: selected ? "rgb(var(--paper))" : "rgb(var(--paper) / 0.6)" },
    strokeWidth: selected ? 2.5 : 1,
  };
  const s = size;
  if (shape === "square") return <rect x={-s} y={-s} width={s * 2} height={s * 2} rx={2} {...common} />;
  if (shape === "diamond") return <path d={`M0 ${-s * 1.3} L${s * 1.3} 0 L0 ${s * 1.3} L${-s * 1.3} 0 Z`} {...common} />;
  if (shape === "triangle") return <path d={`M0 ${-s * 1.3} L${s * 1.2} ${s} L${-s * 1.2} ${s} Z`} {...common} />;
  if (shape === "hexagon") {
    const points = Array.from({ length: 6 }, (_, i) => {
      const a = (Math.PI / 3) * i;
      return `${(Math.cos(a) * s * 1.4).toFixed(1)},${(Math.sin(a) * s * 1.4).toFixed(1)}`;
    }).join(" ");
    return <polygon points={points} {...common} />;
  }
  return <circle r={s} {...common} />;
}

export function KnowledgeGraphView() {
  const graph = useApi(() => getKnowledgeGraph(250));
  const [selected, setSelected] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<KgGraph | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shown = asked && asked.nodes.length ? asked : graph.status === "ready" ? graph.data : null;
  const placed = useMemo(() => (shown ? layout(shown) : null), [shown]);
  const highlighted = new Set(asked?.path ?? []);

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    setError(null);
    try {
      setAsked(await askGraph(question.trim()));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "That could not be answered.");
    } finally {
      setAsking(false);
    }
  }

  if (graph.status === "loading") return <Loading label="Drawing the knowledge graph…" />;
  if (graph.status === "error") return <ErrorMessage message={graph.message} />;
  if (!shown || !placed || shown.nodes.length === 0) {
    return <p className="p-6 text-sm text-muted">The knowledge graph is empty: add a source first.</p>;
  }
  const at = new Map(placed.nodes.map((n) => [n.id, n]));

  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-panel px-4 py-2 text-xs text-soft">
          <h1 className="text-sm font-semibold text-paper">Knowledge graph</h1>
          <span>
            {shown.nodes.length} nodes · {shown.edges.length} edges{shown.truncated ? " (truncated)" : ""}
          </span>
          <form onSubmit={ask} className="flex min-w-[16rem] flex-1 items-center gap-2" role="search">
            <label htmlFor="graph-question" className="sr-only">
              Ask the graph
            </label>
            <input
              id="graph-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Shortest path between A and B · who calls X · what contradicts X"
              className="min-w-0 flex-1 rounded-full border border-line bg-ink px-3 py-1 text-xs outline-none focus:border-signal"
            />
            <button type="submit" disabled={asking} className="rounded-full bg-signal px-3 py-1 text-on-signal disabled:opacity-50">
              {asking ? "Asking…" : "Ask"}
            </button>
            {asked && (
              <button type="button" onClick={() => setAsked(null)} className="text-muted underline">
                Whole graph
              </button>
            )}
          </form>
        </div>
        {(asked?.answer || error) && (
          <p role="status" className="whitespace-pre-wrap border-b border-line px-4 py-2 text-xs text-soft">
            {error ?? asked?.answer}
          </p>
        )}
        <ul aria-label="Legend" className="flex flex-wrap gap-3 px-4 py-2 text-[11px] text-muted">
          {Object.values(LOOKS).map((l) => (
            <li key={l.label} className="flex items-center gap-1.5">
              <svg viewBox="-8 -8 16 16" className="h-3.5 w-3.5" aria-hidden="true">
                <Shape shape={l.shape} color={l.color} size={5} selected={false} />
              </svg>
              {l.label}
            </li>
          ))}
          <li className="flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block w-5 border-t-2 border-dashed border-[#ff6070]" /> contradicts
          </li>
        </ul>
        <svg
          role="img"
          aria-label={`Knowledge graph of ${shown.nodes.length} nodes, clustered by source`}
          viewBox={`${placed.minX} ${placed.minY} ${placed.width} ${placed.height}`}
          className="min-h-[24rem] w-full flex-1"
        >
          <g>
            {shown.edges.map((edge, i) => {
              const a = at.get(edge.source);
              const b = at.get(edge.target);
              if (!a || !b) return null;
              const onPath = highlighted.has(edge.source) && highlighted.has(edge.target);
              return (
                <line
                  key={i}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={onPath ? "#ffffff" : EDGE_COLOR[edge.kind] ?? "#5a6090"}
                  strokeOpacity={onPath ? 0.95 : 0.35 + edge.confidence * 0.3}
                  strokeWidth={onPath ? 2.5 : 1}
                  strokeDasharray={edge.kind === "contradicts" || edge.kind === "supersedes" ? "4 3" : undefined}
                />
              );
            })}
          </g>
          {placed.nodes.map((p) => {
            const { shape, color } = look(p.node.type);
            const isSelected = p.id === selected;
            return (
              <g
                key={p.id}
                transform={`translate(${p.x ?? 0} ${p.y ?? 0})`}
                role="button"
                tabIndex={0}
                aria-label={`${look(p.node.type).label} ${p.node.label}`}
                onClick={() => setSelected(p.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") setSelected(p.id);
                }}
                className="cursor-pointer outline-none"
              >
                <Shape shape={shape} color={color} size={highlighted.has(p.id) ? 9 : 6} selected={isSelected} />
                {(isSelected || highlighted.has(p.id) || p.node.type === "source") && (
                  <text y={-12} textAnchor="middle" className="fill-paper text-[9px]">
                    {p.node.label.length > 32 ? `${p.node.label.slice(0, 31)}…` : p.node.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </main>
      {selected && <NodePanel node={selected} onClose={() => setSelected(null)} onPick={setSelected} />}
    </div>
  );
}

function NodePanel({ node, onClose, onPick }: { node: string; onClose: () => void; onPick: (id: string) => void }) {
  const detail = useApi(() => getKgNode(node), node);
  const base = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
  return (
    <aside aria-label="Node" className="w-80 shrink-0 overflow-y-auto border-l border-line bg-panel">
      {detail.status === "ready" ? (
        <NodeDetail detail={detail.data} base={base} onClose={onClose} onPick={onPick} />
      ) : (
        <p className="p-4 text-xs text-muted">{detail.status === "error" ? detail.message : "Loading…"}</p>
      )}
    </aside>
  );
}

function NodeDetail({ detail, base, onClose, onPick }: { detail: KgNodeDetail; base: string; onClose: () => void; onPick: (id: string) => void }) {
  const question = `Tell me about ${detail.label}${detail.source ? ` (from ${detail.source})` : ""}`;
  return (
    <div className="p-4 text-sm">
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="break-words font-semibold text-paper">{detail.label}</h2>
          <p className="text-xs text-muted">
            {look(detail.type).label} · {detail.type}
            {detail.source ? ` · ${detail.source}` : ""}
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="text-muted hover:text-paper">
          ✕
        </button>
      </header>
      {detail.citation && <p className="mt-2 font-mono text-[11px] text-cyan">{detail.citation}</p>}
      {detail.snippet && (
        <pre className="mt-2 max-h-48 overflow-auto rounded-lg bg-raised p-2 font-mono text-[11px] leading-snug text-soft">{detail.snippet}</pre>
      )}
      <a href={`${base}/chat?ask=${encodeURIComponent(question)}`} className="mt-3 inline-block rounded-full bg-signal px-3 py-1 text-xs text-on-signal">
        Ask about this
      </a>
      <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Edges</h3>
      <ul aria-label="Edges" className="mt-1 space-y-1 text-xs">
        {detail.edges.map((edge, i) =>
          edge.other ? (
            <li key={i}>
              <span className="text-muted">{edge.direction === "out" ? `${edge.kind} →` : `← ${edge.kind}`}</span>{" "}
              <button type="button" onClick={() => onPick(edge.other!.id)} className="text-paper underline decoration-line">
                {edge.other.label}
              </button>
              {edge.evidence && <span className="ml-1 font-mono text-[10px] text-faint">{edge.evidence}</span>}
              {edge.confidence < 1 && <span className="ml-1 text-faint">({Math.round(edge.confidence * 100)}%)</span>}
            </li>
          ) : null,
        )}
      </ul>
    </div>
  );
}
