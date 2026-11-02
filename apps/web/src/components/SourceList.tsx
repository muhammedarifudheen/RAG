"use client";

import type { SourceItem, SourceKind, SourceVersion } from "@atlas/shared";
import { useState } from "react";

import { deleteSource, getSourceVersions, getSources, rollbackSource, setSourceWeight } from "@/lib/api";
import { useApi } from "@/lib/useApi";

const WEIGHTS: Record<number, string> = { 3: "Primary", 2: "Secondary", 1: "Derived" };

const KIND_LABELS: Record<SourceKind, string> = {
  repo: "Repository",
  web: "Web page",
  wikipedia: "Wikipedia",
  crawl: "Website",
  upload: "File",
};

/** What the knowledge base currently holds, with a way to remove each source. */
export function SourceList({ revision, canManage }: { revision: number; canManage: boolean }) {
  const [removals, setRemovals] = useState(0);
  const [removing, setRemoving] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sources = useApi(getSources, `${revision}:${removals}`);
  const [versionsOf, setVersionsOf] = useState<number | null>(null);

  async function weigh(source: SourceItem, weight: number | null) {
    setError(null);
    try {
      await setSourceWeight(source.id, weight);
      setRemovals((value) => value + 1);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not change the weight.");
    }
  }

  async function remove(source: SourceItem) {
    setRemoving(source.id);
    setError(null);
    try {
      await deleteSource(source.id);
      setRemovals((value) => value + 1);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not remove the source.");
    } finally {
      setRemoving(null);
    }
  }

  // The list is secondary on this page: if it cannot be loaded, the form still works.
  if (sources.status !== "ready") return null;

  return (
    <section aria-labelledby="sources-heading" className="mt-10">
      <h2 id="sources-heading" className="text-sm font-semibold text-paper">
        In the knowledge base
      </h2>
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
      {sources.data.length === 0 ? (
        <p className="mt-2 text-sm text-muted">
          {canManage ? "Nothing yet. Add a link or a file above." : "Nothing has been added yet."}
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-line border border-line bg-panel">
          {sources.data.map((source) => (
            <li key={source.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
              <span className="w-20 shrink-0 text-[10px] uppercase tracking-wide text-muted">
                {KIND_LABELS[source.kind]}
              </span>
              <div className="min-w-0 flex-1">
                {source.url ? (
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noreferrer"
                    className="block truncate font-medium text-paper hover:underline"
                  >
                    {source.title}
                  </a>
                ) : (
                  <span className="block truncate font-medium text-paper">{source.title}</span>
                )}
                <span className="text-xs text-muted">
                  {source.files} {source.files === 1 ? "file" : "files"} · {source.symbols}{" "}
                  searchable items{(source.version ?? 1) > 1 && <> · version {source.version}</>}
                  {source.weight && !canManage && (
                    <> · {WEIGHTS[source.weight]} (weight {source.weight})</>
                  )}
                </span>
              </div>
              {canManage && source.weight && (
                <label className="flex items-center gap-1 text-xs text-muted">
                  <span className="sr-only">Weight of {source.title}</span>
                  <select
                    value={source.weight_override ?? 0}
                    onChange={(event) => {
                      const value = Number(event.target.value);
                      void weigh(source, value === 0 ? null : value);
                    }}
                    className="rounded-full border border-line bg-raised px-2 py-1 text-xs text-soft"
                  >
                    <option value={0}>
                      {source.weight_override ? "Automatic" : `Auto: ${WEIGHTS[source.weight]}`}
                    </option>
                    <option value={3}>Primary (3)</option>
                    <option value={2}>Secondary (2)</option>
                    <option value={1}>Derived (1)</option>
                  </select>
                </label>
              )}
              {canManage && (
                <button
                  type="button"
                  onClick={() => setVersionsOf(versionsOf === source.id ? null : source.id)}
                  aria-expanded={versionsOf === source.id}
                  aria-label={`Versions of ${source.title}`}
                  className="px-2 py-1 text-xs text-muted hover:text-paper"
                >
                  Versions
                </button>
              )}
              {canManage && (
                <button
                  type="button"
                  onClick={() => void remove(source)}
                  disabled={removing !== null}
                  aria-label={`Remove ${source.title}`}
                  className="px-2 py-1 text-xs text-muted hover:bg-danger/10 hover:text-danger disabled:cursor-not-allowed disabled:text-faint"
                >
                  {removing === source.id ? "Removing…" : "Remove"}
                </button>
              )}
              {versionsOf === source.id && (
                <Versions
                  source={source}
                  onRestored={() => {
                    setVersionsOf(null);
                    setRemovals((value) => value + 1);
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** A source's last three ingests; any older one can be made current again. */
function Versions({ source, onRestored }: { source: SourceItem; onRestored: () => void }) {
  const versions = useApi(() => getSourceVersions(source.id), String(source.version));
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function restore(version: SourceVersion) {
    setBusy(version.version);
    setError(null);
    try {
      await rollbackSource(source.id, version.version);
      onRestored();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not restore that version.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="basis-full pl-20 text-xs">
      {versions.status === "ready" && (
        <ul aria-label={`Kept versions of ${source.title}`} className="space-y-1">
          {versions.data.map((version) => (
            <li key={version.version} className="flex items-center gap-3 text-muted">
              <span className="font-mono text-soft">v{version.version}</span>
              <span>{new Date(version.created_at).toLocaleString()}</span>
              <span>
                {version.files} files · {version.symbols} items
              </span>
              {version.current ? (
                <span className="text-ok">current</span>
              ) : (
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void restore(version)}
                  className="text-cyan underline disabled:opacity-50"
                >
                  {busy === version.version ? "Restoring…" : `Restore v${version.version}`}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="mt-1 text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
