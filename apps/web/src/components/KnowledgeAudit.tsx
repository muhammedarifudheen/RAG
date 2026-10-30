"use client";

import type { KnowledgeAudit as Audit } from "@atlas/shared";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getAdminToken, runKnowledgeAudit } from "@/lib/api";

const REMARK = [remarkGfm];

/** The newest health check of the knowledge base, and, for the admin, a way to run one. */
export function KnowledgeAudit({ audit: initial }: { audit: Audit | null }) {
  const [audit, setAudit] = useState(initial);
  const [admin, setAdmin] = useState(false);
  const [state, setState] = useState<{ name: "idle" | "running" } | { name: "failed"; message: string }>({
    name: "idle",
  });
  // Read after mounting: the token lives in this browser only.
  useEffect(() => setAdmin(Boolean(getAdminToken())), []);

  async function run() {
    setState({ name: "running" });
    try {
      setAudit(await runKnowledgeAudit());
      setState({ name: "idle" });
    } catch (error) {
      setState({ name: "failed", message: error instanceof Error ? error.message : "The audit failed." });
    }
  }

  return (
    <section aria-labelledby="knowledge-audit">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="knowledge-audit" className="text-base font-semibold">
          Knowledge-base audit
        </h2>
        {admin && (
          <button
            type="button"
            onClick={() => void run()}
            disabled={state.name === "running"}
            className="rounded-full border border-line px-3 py-1 text-xs text-cyan hover:border-cyan/60 disabled:animate-pulse disabled:opacity-60"
          >
            {state.name === "running" ? "Auditing every source…" : "Run audit now"}
          </button>
        )}
      </div>
      {audit ? (
        <>
          <p className="mt-1 text-sm text-soft">
            {audit.sources} {audit.sources === 1 ? "source" : "sources"} audited on{" "}
            {new Date(audit.created_at).toLocaleString()} by {audit.model}: coverage, staleness,
            overlap and the questions each cannot answer.
          </p>
          <div className="markdown mt-3 overflow-x-auto text-sm">
            <ReactMarkdown remarkPlugins={REMARK}>{audit.report}</ReactMarkdown>
          </div>
        </>
      ) : (
        <p className="mt-2 text-sm text-soft">
          No audit yet. One runs every Monday and after each server deploy.
        </p>
      )}
      {state.name === "failed" && <p className="mt-2 text-sm text-danger">{state.message}</p>}
    </section>
  );
}
