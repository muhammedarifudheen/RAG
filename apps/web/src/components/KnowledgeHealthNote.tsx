"use client";

import type { KnowledgeHealth } from "@atlas/shared";
import Link from "next/link";

/**
 * The knowledge-health note, for one chat or everything logged: the top recurring gaps,
 * the sources to add or refresh, and one question answered surprisingly well.
 */
export function KnowledgeHealthNote({
  health,
  title,
  onClose,
}: {
  health: KnowledgeHealth;
  title: string;
  onClose?: () => void;
}) {
  return (
    <section aria-label="Knowledge health" className="slab p-4 text-sm">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-display text-base font-semibold">{title}</h2>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close the knowledge health note"
            className="label rounded-full px-2 py-1 text-muted hover:bg-raised hover:text-paper"
          >
            ✕
          </button>
        )}
      </div>
      <p className="mt-1 text-xs text-muted">
        From {health.answers} logged {health.answers === 1 ? "answer" : "answers"}
        {health.scope === "chat" ? " in this chat" : ""}.
      </p>

      <div className="mt-3 grid gap-4 sm:grid-cols-3">
        <div>
          <h3 className="label text-muted">Recurring gaps</h3>
          <ul aria-label="Recurring gaps" className="mt-1.5 space-y-1 text-soft">
            {health.gaps.length ? (
              health.gaps.map((gap) => (
                <li key={gap.question}>
                  {gap.question} <span className="text-faint">({gap.times}×)</span>
                </li>
              ))
            ) : (
              <li className="text-faint">None yet.</li>
            )}
          </ul>
        </div>
        <div>
          <h3 className="label text-muted">Add or refresh</h3>
          <ul aria-label="Sources to add or refresh" className="mt-1.5 space-y-1 text-soft">
            {health.sources.length ? (
              health.sources.map((source) => (
                <li key={`${source.action}:${source.source}`}>
                  <span className="text-signal">{source.action === "add" ? "Add" : "Refresh"}</span>{" "}
                  {source.action === "add" && /^https?:\/\//.test(source.source) ? (
                    <Link href={`/?add=${encodeURIComponent(source.source)}`} className="text-cyan hover:underline">
                      {source.source}
                    </Link>
                  ) : (
                    source.source
                  )}
                  {source.why && <span className="block text-xs text-faint">{source.why}</span>}
                </li>
              ))
            ) : (
              <li className="text-faint">Nothing to add yet.</li>
            )}
          </ul>
        </div>
        <div>
          <h3 className="label text-muted">Answered surprisingly well</h3>
          <p className="mt-1.5 text-soft">
            {health.well_answered ? health.well_answered.question : (
              <span className="text-faint">Nothing stands out yet.</span>
            )}
          </p>
        </div>
      </div>
    </section>
  );
}
