"use client";

import type { Webhook, WebhookCreated, WebhookEvent } from "@atlas/shared";
import { useState, type FormEvent } from "react";

import { API_BASE, createWebhook, deleteWebhook, exportAnswers, getWebhooks } from "@/lib/api";
import { useApi } from "@/lib/useApi";

const EVENTS: { value: WebhookEvent; label: string }[] = [
  { value: "ingest", label: "Ingests" },
  { value: "query", label: "Answers" },
  { value: "gap", label: "Gaps" },
  { value: "health", label: "Health" },
];

/** The server's own address, for the instructions (the API is proxied under /api locally). */
function serverAddress(): string {
  if (/^https?:\/\//.test(API_BASE)) return API_BASE;
  return typeof window === "undefined" ? API_BASE : `${window.location.origin}${API_BASE}`;
}

/** Connecting Atlas to other tools: OpenAI clients, MCP agents, webhooks and exports. */
export function Integrations() {
  const [revision, setRevision] = useState(0);
  const hooks = useApi(getWebhooks, String(revision));
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<WebhookEvent[]>(["ingest", "query", "gap", "health"]);
  const [created, setCreated] = useState<WebhookCreated | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const server = serverAddress();

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setCreated(await createWebhook(url.trim(), events));
      setUrl("");
      setRevision((value) => value + 1);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not add the webhook.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(hook: Webhook) {
    if (hook.id === null) return;
    setError(null);
    try {
      await deleteWebhook(hook.id);
      setRevision((value) => value + 1);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not remove the webhook.");
    }
  }

  async function download() {
    setError(null);
    try {
      const blob = await exportAnswers();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "atlas-qa.jsonl";
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not export the answers.");
    }
  }

  function toggle(value: WebhookEvent) {
    setEvents((current) =>
      current.includes(value) ? current.filter((e) => e !== value) : [...current, value],
    );
  }

  return (
    <section aria-labelledby="integrations-heading" className="mt-10">
      <h2 id="integrations-heading" className="text-sm font-semibold text-paper">
        Integrations
      </h2>
      <dl className="mt-3 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
        <dt className="text-muted">OpenAI-compatible</dt>
        <dd className="min-w-0">
          Base URL <code className="break-all font-mono text-cyan">{server}/v1</code>, model{" "}
          <code className="font-mono">atlas</code> (grounded) or{" "}
          <code className="font-mono">atlas-open</code>.
        </dd>
        <dt className="text-muted">MCP server</dt>
        <dd className="min-w-0">
          <code className="break-all font-mono text-cyan">{server}/mcp</code>: tools{" "}
          <code className="font-mono">search_atlas</code>, <code className="font-mono">ask_atlas</code>{" "}
          and <code className="font-mono">list_sources</code>.
        </dd>
        <dt className="text-muted">GitHub re-index</dt>
        <dd className="min-w-0">
          A repository webhook (push events, JSON) to{" "}
          <code className="break-all font-mono text-cyan">{server}/hooks/github</code>, with the
          server&apos;s GITHUB_WEBHOOK_SECRET.
        </dd>
        <dt className="text-muted">Exports</dt>
        <dd className="flex flex-wrap gap-3">
          <button type="button" onClick={download} className="text-cyan underline">
            Answers as JSONL
          </button>
          <a href={`${server}/export/audit.md`} target="_blank" rel="noreferrer" className="text-cyan underline">
            Audit report (Markdown)
          </a>
        </dd>
      </dl>

      <h3 className="mt-6 text-xs font-semibold uppercase tracking-wide text-muted">Webhooks</h3>
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
      {created && (
        <p role="status" className="mt-2 border border-ok/40 bg-ok/10 p-3 text-sm text-ok">
          Added. Its signing secret, shown only now:{" "}
          <code className="break-all font-mono" aria-label="Webhook secret">
            {created.secret}
          </code>
        </p>
      )}
      {hooks.status === "ready" && hooks.data.length > 0 && (
        <ul aria-label="Webhooks" className="mt-2 divide-y divide-line border border-line">
          {hooks.data.map((hook) => (
            <li key={hook.id ?? hook.url} className="flex items-center gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate font-mono text-xs">{hook.url}</span>
              <span className="text-xs text-muted">{hook.events.join(", ")}</span>
              {hook.last_status !== null && hook.last_status !== undefined && (
                <span
                  className={`text-xs ${hook.last_status >= 200 && hook.last_status < 300 ? "text-ok" : "text-danger"}`}
                >
                  {hook.last_status || "unreachable"}
                </span>
              )}
              {hook.configured ? (
                <span className="text-xs text-faint">set on the server</span>
              ) : (
                <button
                  type="button"
                  onClick={() => remove(hook)}
                  aria-label={`Remove webhook ${hook.url}`}
                  className="text-xs text-danger underline"
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={add} className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <label htmlFor="webhook-url" className="sr-only">
          Webhook address
        </label>
        <input
          id="webhook-url"
          type="url"
          required
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://example.com/atlas-events"
          className="min-w-0 flex-1 border border-line-strong bg-ink px-3 py-1.5 text-sm outline-none focus:border-signal"
        />
        <div className="flex gap-3 text-xs text-soft">
          {EVENTS.map((event) => (
            <label key={event.value} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={events.includes(event.value)}
                onChange={() => toggle(event.value)}
              />
              {event.label}
            </label>
          ))}
        </div>
        <button
          type="submit"
          disabled={busy || !url.trim() || events.length === 0}
          className="border border-line-strong bg-panel px-3 py-1.5 text-sm hover:bg-raised disabled:text-faint"
        >
          Add webhook
        </button>
      </form>
    </section>
  );
}
