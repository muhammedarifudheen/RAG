"use client";

import type { SourceItem, SourceKind } from "@atlas/shared";
import { useState } from "react";

import { deleteSource, getSources } from "@/lib/api";
import { useApi } from "@/lib/useApi";

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
            <li key={source.id} className="flex items-center gap-3 px-3 py-2 text-sm">
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
                  searchable items
                </span>
              </div>
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
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
