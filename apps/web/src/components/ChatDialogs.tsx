"use client";

import type { AnswerStyle } from "@atlas/shared";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { createShare } from "@/lib/api";
import { withoutImageData, type ChatSettings, type SavedChat } from "@/lib/chats";
import { copyText } from "@/lib/exporting";

/** A modal built on <dialog>: Escape and the close button end it, focus stays inside. */
export function Dialog({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    return () => dialog?.close();
  }, []);

  return (
    <dialog
      ref={ref}
      aria-label={title}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose(); // a click on the backdrop
      }}
      className={`m-auto w-[calc(100%-2rem)] ${wide ? "max-w-2xl" : "max-w-lg"} border border-line-strong bg-panel p-0 text-paper shadow-block backdrop:bg-black/70 backdrop:backdrop-blur-sm`}
    >
      <header className="flex items-center justify-between border-b border-line px-5 py-3">
        <h2 className="font-display text-sm font-bold uppercase tracking-[0.12em]">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${title.toLowerCase()}`}
          className="px-2 py-1 text-muted hover:text-paper"
        >
          ✕
        </button>
      </header>
      <div className="max-h-[75vh] overflow-y-auto px-5 py-4">{children}</div>
    </dialog>
  );
}

const STYLES: { value: AnswerStyle; label: string; hint: string }[] = [
  { value: "concise", label: "Concise", hint: "Short and to the point" },
  { value: "balanced", label: "Balanced", hint: "As much as the question needs" },
  { value: "detailed", label: "Detailed", hint: "Thorough, with examples" },
];

export function SettingsDialog({
  settings,
  onChange,
  onClose,
  onExportAll,
  onImport,
  onDeleteAll,
  chatCount,
}: {
  settings: ChatSettings;
  onChange: (next: ChatSettings) => void;
  onClose: () => void;
  onExportAll: () => void;
  onImport: (file: File) => void;
  onDeleteAll: () => void;
  chatCount: number;
}) {
  const importer = useRef<HTMLInputElement>(null);
  const [confirming, setConfirming] = useState(false);
  const set = (patch: Partial<ChatSettings>) => onChange({ ...settings, ...patch });
  const temperature = settings.temperature ?? 1;

  return (
    <Dialog title="Settings" onClose={onClose}>
      <section>
        <h3 className="label text-muted">Answer length</h3>
        <div role="radiogroup" aria-label="Answer length" className="mt-2 grid grid-cols-3 gap-2">
          {STYLES.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={settings.style === option.value}
              onClick={() => set({ style: option.value })}
              className={`border px-3 py-2 text-left transition-colors ${
                settings.style === option.value
                  ? "border-signal bg-signal/10"
                  : "border-line hover:border-line-strong"
              }`}
            >
              <span className="block text-sm font-medium">{option.label}</span>
              <span className="block text-[11px] text-muted">{option.hint}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="mt-6">
        <h3 className="label text-muted">Creativity</h3>
        <label className="mt-2 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={settings.temperature === null}
            onChange={(event) => set({ temperature: event.target.checked ? null : 0.7 })}
            className="accent-signal"
          />
          Let each model use its own default
        </label>
        <div className={`mt-3 ${settings.temperature === null ? "opacity-40" : ""}`}>
          <label htmlFor="temperature" className="flex justify-between text-xs text-soft">
            <span>Temperature</span>
            <span className="font-mono text-acid">{temperature.toFixed(1)}</span>
          </label>
          <input
            id="temperature"
            type="range"
            min={0}
            max={2}
            step={0.1}
            value={temperature}
            disabled={settings.temperature === null}
            onChange={(event) => set({ temperature: Number(event.target.value) })}
            className="mt-1 w-full accent-signal"
          />
          <p className="flex justify-between text-[11px] text-muted">
            <span>Precise</span>
            <span>Creative</span>
          </p>
        </div>
      </section>

      <section className="mt-6">
        <label htmlFor="instructions" className="label block text-muted">
          Custom instructions
        </label>
        <p className="mt-1 text-xs text-muted">
          Sent with every message: who you are, how you like answers, a language to reply in.
        </p>
        <textarea
          id="instructions"
          value={settings.instructions}
          onChange={(event) => set({ instructions: event.target.value.slice(0, 4000) })}
          rows={4}
          placeholder="e.g. I'm a Python developer. Reply in British English, with code examples."
          className="mt-2 w-full resize-y border border-line bg-ink px-3 py-2 text-sm outline-none placeholder:text-faint focus:border-signal"
        />
        <p className="text-right text-[11px] text-faint">{settings.instructions.length}/4000</p>
      </section>

      <section className="mt-4">
        <h3 className="label text-muted">Voice</h3>
        <label className="mt-2 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={settings.speak}
            onChange={(event) => set({ speak: event.target.checked })}
            className="accent-signal"
          />
          Read each new answer aloud
        </label>
      </section>

      <section className="mt-6 border-t border-line pt-4">
        <h3 className="label text-muted">Your chats</h3>
        <p className="mt-1 text-xs text-muted">
          {chatCount} {chatCount === 1 ? "chat is" : "chats are"} kept in this browser only.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onExportAll}
            disabled={chatCount === 0}
            className="border border-line px-3 py-1.5 text-xs hover:border-line-strong disabled:opacity-40"
          >
            Export all chats
          </button>
          <button
            type="button"
            onClick={() => importer.current?.click()}
            className="border border-line px-3 py-1.5 text-xs hover:border-line-strong"
          >
            Import chats
          </button>
          <input
            ref={importer}
            type="file"
            accept="application/json,.json"
            className="hidden"
            aria-label="Chats file to import"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onImport(file);
              event.target.value = "";
            }}
          />
          {confirming ? (
            <span className="flex items-center gap-2 text-xs">
              Delete every chat?
              <button
                type="button"
                onClick={() => {
                  onDeleteAll();
                  setConfirming(false);
                }}
                className="border border-danger px-2 py-1 text-danger hover:bg-danger/10"
              >
                Yes, delete
              </button>
              <button type="button" onClick={() => setConfirming(false)} className="px-2 py-1 text-muted">
                Keep them
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              disabled={chatCount === 0}
              className="border border-line px-3 py-1.5 text-xs text-danger hover:border-danger/60 disabled:opacity-40"
            >
              Delete all chats
            </button>
          )}
        </div>
      </section>
    </Dialog>
  );
}

/** Where a shared chat can be read: this site's /share page. */
export function shareUrl(id: string): string {
  const base = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
  return `${window.location.origin}${base}/share/?id=${encodeURIComponent(id)}`;
}

export function ShareDialog({ chat, onClose }: { chat: SavedChat; onClose: () => void }) {
  const [state, setState] = useState<
    { status: "creating" } | { status: "ready"; url: string } | { status: "error"; message: string }
  >({ status: "creating" });
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let current = true;
    // Attached images stay private: only their names are shared.
    const { title, messages } = withoutImageData(chat);
    createShare(title, messages)
      .then((share) => current && setState({ status: "ready", url: shareUrl(share.id) }))
      .catch(
        (error: unknown) =>
          current &&
          setState({
            status: "error",
            message: error instanceof Error ? error.message : "The chat could not be shared.",
          }),
      );
    return () => {
      current = false;
    };
  }, [chat]);

  return (
    <Dialog title="Share chat" onClose={onClose}>
      <p className="text-sm text-soft">
        Anyone with the link can read this conversation as it is now. Attached images are not
        included. On the free server, shared links last until it restarts.
      </p>
      {state.status === "creating" && (
        <p className="label mt-4 animate-pulse text-muted">Creating the link…</p>
      )}
      {state.status === "error" && (
        <p role="alert" className="mt-4 border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {state.message}
        </p>
      )}
      {state.status === "ready" && (
        <div className="mt-4 flex gap-2">
          <input
            readOnly
            value={state.url}
            aria-label="Link to the shared chat"
            onFocus={(event) => event.target.select()}
            className="min-w-0 flex-1 border border-line bg-ink px-3 py-2 font-mono text-xs"
          />
          <button
            type="button"
            onClick={() => {
              void copyText(state.url).then(() => setCopied(true));
            }}
            className="bg-signal px-4 py-2 text-sm font-semibold text-ink hover:bg-signal-hover"
          >
            {copied ? "Copied" : "Copy link"}
          </button>
        </div>
      )}
    </Dialog>
  );
}

export const SHORTCUTS: [string, string][] = [
  ["Enter", "Send"],
  ["Shift + Enter", "New line"],
  ["Esc", "Stop the answer, or close a dialog"],
  ["/", "Focus the message box"],
  ["↑ in an empty box", "Edit your last message"],
  ["Ctrl + Shift + O", "New chat"],
  ["Ctrl + K", "Search chats"],
  ["Ctrl + Shift + C", "Copy the last answer"],
  ["Ctrl + /", "Show these shortcuts"],
];

export function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog title="Keyboard shortcuts" onClose={onClose}>
      <dl className="divide-y divide-line">
        {SHORTCUTS.map(([keys, action]) => (
          <div key={keys} className="flex items-center justify-between gap-4 py-2 text-sm">
            <dt className="text-soft">{action}</dt>
            <dd>
              <kbd className="border border-line-strong bg-raised px-2 py-0.5 font-mono text-[11px] text-acid">
                {keys}
              </kbd>
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-muted">On a Mac, use ⌘ in place of Ctrl.</p>
    </Dialog>
  );
}
