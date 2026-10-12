"use client";

import type { FileGraph, FileNode } from "@atlas/shared";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";

import "@xyflow/react/dist/style.css";

import { getFile, getFileGraph } from "@/lib/api";
import { forceLayout } from "@/lib/layout";
import { useApi } from "@/lib/useApi";

import { ErrorMessage, Loading, NothingIngested } from "./States";

const RED = "#dc2626";
const GREY = "#94a3b8";

type FileFlowNode = Node<{ label: string; path: string }>;

/** The last two path segments: enough to tell apart files that share a name. */
function shortName(path: string): string {
  return path.split("/").slice(-2).join("/");
}

function toFlow(graph: FileGraph): { nodes: FileFlowNode[]; edges: Edge[] } {
  const positions = forceLayout(
    graph.nodes.map((node) => String(node.id)),
    graph.edges.map((edge) => ({ source: String(edge.source), target: String(edge.target) })),
  );

  const nodes = graph.nodes.map<FileFlowNode>((file) => ({
    id: String(file.id),
    position: positions.get(String(file.id)) ?? { x: 0, y: 0 },
    data: { label: shortName(file.path), path: file.path },
    className: file.in_cycle ? "file-node in-cycle" : "file-node",
  }));

  const edges = graph.edges.map<Edge>((edge) => {
    const color = edge.in_cycle ? RED : GREY;
    return {
      id: `${edge.source}-${edge.target}`,
      source: String(edge.source),
      target: String(edge.target),
      className: edge.in_cycle ? "in-cycle" : undefined,
      animated: edge.in_cycle,
      // Dashed when the files are linked by imports alone, solid once there are calls.
      style: {
        stroke: color,
        strokeWidth: edge.in_cycle ? 2 : 1.25,
        strokeDasharray: edge.calls === 0 ? "5 4" : undefined,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color },
    };
  });

  return { nodes, edges };
}

export function FileGraphView() {
  const graph = useApi(getFileGraph);
  const [nodes, setNodes, onNodesChange] = useNodesState<FileFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selected, setSelected] = useState<FileNode | null>(null);

  const data = graph.status === "ready" ? graph.data : null;
  const flow = useMemo(() => (data ? toFlow(data) : null), [data]);

  useEffect(() => {
    if (!flow) return;
    setNodes(flow.nodes);
    setEdges(flow.edges);
  }, [flow, setNodes, setEdges]);

  if (graph.status === "loading") return <Loading label="Loading the dependency graph…" />;
  if (graph.status === "error") return <ErrorMessage message={graph.message} />;
  if (graph.data.nodes.length === 0) return <NothingIngested />;

  const { nodes: files, edges: dependencies, cycles } = graph.data;

  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 border-b border-slate-200 bg-white px-4 py-2 text-xs text-slate-600">
          <h1 className="text-sm font-semibold text-slate-900">File dependencies</h1>
          <p data-testid="graph-summary">
            {files.length} files · {dependencies.length} dependencies ·{" "}
            <span className={cycles.length > 0 ? "font-semibold text-red-700" : ""}>
              {cycles.length} {cycles.length === 1 ? "cycle" : "cycles"}
            </span>
          </p>
          <ul className="ml-auto flex gap-4">
            <li>
              <span className="mr-1 inline-block w-5 border-t-2 border-slate-400 align-middle" />
              calls
            </li>
            <li>
              <span className="mr-1 inline-block w-5 border-t-2 border-dashed border-slate-400 align-middle" />
              imports only
            </li>
            <li>
              <span className="mr-1 inline-block w-5 border-t-2 border-red-600 align-middle" />
              in a cycle
            </li>
          </ul>
        </div>

        <div className="min-h-[32rem] flex-1" data-testid="file-graph">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_event, node) =>
              setSelected(files.find((file) => String(file.id) === node.id) ?? null)
            }
            onPaneClick={() => setSelected(null)}
            nodesConnectable={false}
            fitView
            minZoom={0.1}
          >
            <Background />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable nodeColor={(node) => (node.className?.includes("in-cycle") ? RED : GREY)} />
          </ReactFlow>
        </div>
      </main>

      {/* Always present, so selecting a file does not resize the graph under the pointer. */}
      <aside
        aria-label="File symbols"
        className="flex h-[calc(100vh-3.5rem)] w-80 shrink-0 flex-col border-l border-slate-200 bg-white"
      >
        {selected ? (
          <FilePanel file={selected} onClose={() => setSelected(null)} />
        ) : (
          <p className="p-4 text-sm text-slate-500">Click a file to see its symbols.</p>
        )}
      </aside>
    </div>
  );
}

function FilePanel({ file, onClose }: { file: FileNode; onClose: () => void }) {
  const detail = useApi(() => getFile(file.path), file.path);

  return (
    <>
      <header className="flex items-start justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div className="min-w-0">
          <h2 className="break-all font-mono text-xs font-semibold">{file.path}</h2>
          <p className="mt-1 text-xs text-slate-500">
            {file.language} · {file.loc} lines
            {file.in_cycle && <span className="ml-2 font-semibold text-red-700">in a cycle</span>}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close file panel"
          className="rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-900"
        >
          ✕
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        {detail.status === "loading" && <p className="text-sm text-slate-500">Loading symbols…</p>}
        {detail.status === "error" && (
          <p role="alert" className="text-sm text-red-700">
            {detail.message}
          </p>
        )}
        {detail.status === "ready" && detail.data.symbols.length === 0 && (
          <p className="text-sm text-slate-500">This file defines no symbols.</p>
        )}
        {detail.status === "ready" && detail.data.symbols.length > 0 && (
          <ul className="space-y-2">
            {detail.data.symbols.map((symbol) => (
              <li key={symbol.id} className="text-sm">
                <p className="flex items-baseline gap-2">
                  <span className="w-14 shrink-0 text-[10px] uppercase tracking-wide text-slate-400">
                    {symbol.kind}
                  </span>
                  <span className="break-all font-mono text-xs font-medium">{symbol.name}</span>
                </p>
                <p className="pl-16 text-[11px] text-slate-400">
                  lines {symbol.start_line}–{symbol.end_line}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
