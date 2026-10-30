"use client";

import type { AnswerFormat, AnswerStyle } from "@atlas/shared";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { createShare } from "@/lib/api";
import {
  AI_SERVICES,
  DEFAULT_SETTINGS,
  PERSONAS,
  loadActiveServices,
  withoutImageData,
  type ChatSettings,
  type SavedChat,
} from "@/lib/chats";
import { copyText } from "@/lib/exporting";
import { applyTheme, currentTheme } from "@/lib/theme";

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
      className={`m-auto w-[calc(100%-2rem)] ${wide ? "max-w-2xl" : "max-w-lg"} rounded-[24px] border border-line bg-panel/95 p-0 text-paper shadow-float backdrop:bg-[rgba(22,24,39,0.22)] backdrop:backdrop-blur-sm`}
    >
      <header className="flex items-center justify-between border-b border-line px-5 py-3">
        <h2 className="font-display text-[15px] font-semibold">{title}</h2>
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
  const [tab, setTab] = useState<SettingsTab>("answers");

  return (
    <Dialog title="Settings" onClose={onClose} wide>
      <div role="tablist" aria-label="Settings sections" className="mb-5 flex flex-wrap gap-1 rounded-full bg-raised p-1">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
            className={`flex-1 rounded-full px-3 py-1.5 text-[13px] transition-colors ${
              tab === item.id ? "bg-panel text-paper shadow-block" : "text-muted hover:text-paper"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "models" && <ModelsTab settings={settings} set={set} />}
      {tab === "retrieval" && <RetrievalTab settings={settings} set={set} />}
      {tab === "transparency" && <TransparencyTab settings={settings} set={set} />}

      {tab === "answers" && (
        <>
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

          <GenerationControls settings={settings} set={set} />

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
        </>
      )}
    </Dialog>
  );
}

type SettingsTab = "answers" | "models" | "retrieval" | "transparency";
type Patch = (patch: Partial<ChatSettings>) => void;

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "answers", label: "Answers" },
  { id: "models", label: "Models" },
  { id: "retrieval", label: "Retrieval" },
  { id: "transparency", label: "Transparency" },
];

const FORMATS: { value: AnswerFormat; label: string }[] = [
  { value: "markdown", label: "Rich (Markdown)" },
  { value: "plain", label: "Plain text" },
  { value: "json", label: "JSON" },
];

const LENGTHS: { value: number | null; label: string }[] = [
  { value: null, label: "Model default" },
  { value: 500, label: "Short (500 tokens)" },
  { value: 1500, label: "Medium (1,500)" },
  { value: 4000, label: "Long (4,000)" },
  { value: 8000, label: "Very long (8,000)" },
];

function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 py-2">
      <span>
        <span className="block text-sm">{label}</span>
        {hint && <span className="block text-xs text-muted">{hint}</span>}
      </span>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1 h-4 w-4 shrink-0 accent-signal"
      />
    </label>
  );
}

function Slider({
  id,
  label,
  value,
  shown,
  min,
  max,
  step,
  onChange,
  ends,
}: {
  id: string;
  label: string;
  value: number;
  shown: string;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  ends?: [string, string];
}) {
  return (
    <div className="py-2">
      <label htmlFor={id} className="flex justify-between text-sm">
        <span>{label}</span>
        <span className="font-mono text-xs text-signal">{shown}</span>
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-1 w-full accent-signal"
      />
      {ends && (
        <p className="flex justify-between text-[11px] text-muted">
          <span>{ends[0]}</span>
          <span>{ends[1]}</span>
        </p>
      )}
    </div>
  );
}

function Select<T extends string | number | null>({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const index = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );
  return (
    <div className="py-2">
      <label htmlFor={id} className="block text-sm">
        {label}
      </label>
      <select
        id={id}
        value={index}
        onChange={(event) => onChange(options[Number(event.target.value)].value)}
        className="mt-1 w-full border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-signal"
      >
        {options.map((option, i) => (
          <option key={String(option.value)} value={i}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Role, output format and answer length (the Answers tab). */
function GenerationControls({ settings, set }: { settings: ChatSettings; set: Patch }) {
  return (
    <section className="mt-6">
      <h3 className="label text-muted">Generation</h3>
      <div className="mt-1 grid gap-x-4 sm:grid-cols-3">
        <Select
          id="persona"
          label="Persona"
          value={settings.persona}
          options={PERSONAS.map((p) => ({ value: p.id, label: p.label }))}
          onChange={(persona) => set({ persona })}
        />
        <Select
          id="format"
          label="Output format"
          value={settings.format}
          options={FORMATS}
          onChange={(format) => set({ format })}
        />
        <Select
          id="max-tokens"
          label="Maximum length"
          value={settings.maxTokens}
          options={LENGTHS}
          onChange={(maxTokens) => set({ maxTokens })}
        />
      </div>
    </section>
  );
}

/** Which AI services answer, how many agents, and who merges. */
function ModelsTab({ settings, set }: { settings: ChatSettings; set: Patch }) {
  const [active] = useState(loadActiveServices);
  const chosen = new Set(settings.services);
  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    set({ services: AI_SERVICES.map((s) => s.id).filter((s) => next.has(s)) });
  };
  const size = settings.councilSize ?? 12;
  return (
    <>
      <section>
        <div className="flex items-baseline justify-between">
          <h3 className="label text-muted">AI services</h3>
          <button
            type="button"
            onClick={() => set({ services: [] })}
            className="text-xs text-cyan hover:underline"
          >
            Use every service
          </button>
        </div>
        <p className="mt-1 text-xs text-muted">
          {settings.services.length
            ? `Only the ${settings.services.length} chosen services answer.`
            : "Every service with a key answers. Choose some to use only those."}
          {active.length > 0 && " A green dot marks the services this server has."}
        </p>
        <ul aria-label="AI services" className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {AI_SERVICES.map((service) => (
            <li key={service.id}>
              <label
                className={`flex cursor-pointer items-center gap-2 border px-3 py-2 text-sm transition-colors ${
                  chosen.has(service.id) ? "border-signal bg-signal/5" : "border-line hover:border-line-strong"
                }`}
              >
                <input
                  type="checkbox"
                  checked={chosen.has(service.id)}
                  onChange={() => toggle(service.id)}
                  className="accent-signal"
                />
                <span className="flex-1">{service.label}</span>
                {active.includes(service.id) && (
                  <span aria-label="available" className="h-1.5 w-1.5 rounded-full bg-ok" />
                )}
              </label>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-6">
        <h3 className="label text-muted">The council</h3>
        <Slider
          id="council-size"
          label="Agents per question"
          value={size}
          shown={size === 1 ? "1 (one model)" : String(size)}
          min={1}
          max={12}
          step={1}
          onChange={(value) => set({ councilSize: value === 12 ? null : value })}
          ends={["Fastest", "Most thorough"]}
        />
        <Select
          id="merger"
          label="Merged by"
          value={settings.merger}
          options={[
            { value: "", label: "The quickest agent that answered" },
            ...AI_SERVICES.map((s) => ({ value: s.id, label: s.label })),
          ]}
          onChange={(merger) => set({ merger })}
        />
      </section>
    </>
  );
}

/** Retrieval-augmented generation: the knowledge base and the web. */
function RetrievalTab({ settings, set }: { settings: ChatSettings; set: Patch }) {
  const minScore = settings.minScore ?? 0.3;
  const rerankCutoff = settings.rerankCutoff ?? 4;
  return (
    <>
      <section>
        <h3 className="label text-muted">Your knowledge base</h3>
        <Toggle
          label="Strict sources only"
          hint="Answer only from your sources and attached files, with a citation ending every sentence of fact; conflicts between sources are flagged, and when the sources fall short it says exactly what is missing. No web, no general knowledge."
          checked={settings.strict}
          onChange={(strict) => set({ strict })}
        />
        <Toggle
          label="Deep research for complex questions"
          hint="For comparisons, flows through the code and many-part questions, an agent searches, reads the best spans and takes notes (up to 6 steps) before the answer is written. The composer's Research switch does it for every question."
          checked={settings.researchAuto}
          onChange={(researchAuto) => set({ researchAuto })}
        />
        <Toggle
          label="Search your sources"
          hint="Answer from the ingested repositories, pages and documents, citing exact lines."
          checked={settings.useSources}
          onChange={(useSources) => set({ useSources })}
        />
        <div className={settings.useSources ? "" : "pointer-events-none opacity-40"}>
          <Toggle
            label="Plan several searches per question"
            hint="A fast model rewrites the question into keywords, a hypothetical answer (HyDE) and a variant; their results are fused, so more of the right excerpts are found."
            checked={settings.planQueries}
            onChange={(planQueries) => set({ planQueries })}
          />
          <Toggle
            label="Judge each excerpt's relevance"
            hint="Fast models score every candidate excerpt 0-10 for the question; the best come first and those under the cut-off are left out."
            checked={settings.rerank}
            onChange={(rerank) => set({ rerank })}
          />
          <div className={settings.rerank ? "" : "pointer-events-none opacity-40"}>
            <Slider
              id="rerank-cutoff"
              label="Judge's cut-off"
              value={rerankCutoff}
              shown={`${rerankCutoff}/10`}
              min={0}
              max={10}
              step={1}
              onChange={(value) => set({ rerankCutoff: value === 4 ? null : value })}
              ends={["Keep more", "Only direct answers"]}
            />
            <Toggle
              label="Then rank the kept excerpts together"
              hint="One more call compares the excerpts the judge kept side by side and orders them by how directly they answer, so the model reads the best first."
              checked={settings.rankPassages}
              onChange={(rankPassages) => set({ rankPassages })}
            />
          </div>
          <Slider
            id="top-k"
            label="Excerpts per question (top-k)"
            value={settings.topK}
            shown={String(settings.topK)}
            min={1}
            max={20}
            step={1}
            onChange={(topK) => set({ topK })}
          />
          <Slider
            id="min-score"
            label="Relevance threshold"
            value={minScore}
            shown={minScore.toFixed(2)}
            min={0}
            max={0.9}
            step={0.05}
            onChange={(value) => set({ minScore: value === 0.3 ? null : value })}
            ends={["Include more", "Only close matches"]}
          />
        </div>
      </section>
      <section className="mt-6">
        <h3 className="label text-muted">The web</h3>
        <Toggle
          label="Search the web before answering"
          hint="Google News and Wikipedia (plus Tavily or Brave when keyed), so answers carry today's facts."
          checked={settings.webSearch}
          onChange={(webSearch) => set({ webSearch })}
        />
      </section>
      <button
        type="button"
        onClick={() =>
          set({
            useSources: DEFAULT_SETTINGS.useSources,
            topK: DEFAULT_SETTINGS.topK,
            minScore: DEFAULT_SETTINGS.minScore,
            webSearch: DEFAULT_SETTINGS.webSearch,
            strict: DEFAULT_SETTINGS.strict,
            planQueries: DEFAULT_SETTINGS.planQueries,
            rerank: DEFAULT_SETTINGS.rerank,
            rankPassages: DEFAULT_SETTINGS.rankPassages,
            rerankCutoff: DEFAULT_SETTINGS.rerankCutoff,
          })
        }
        className="mt-4 text-xs text-cyan hover:underline"
      >
        Reset retrieval to defaults
      </button>
    </>
  );
}

/** What Atlas shows of how an answer was made. */
function TransparencyTab({ settings, set }: { settings: ChatSettings; set: Patch }) {
  return (
    <section>
      <h3 className="label text-muted">Show your work</h3>
      <Toggle
        label="Show every agent's own draft"
        hint="Under each merged answer: what each council agent wrote, and how long it took."
        checked={settings.showDrafts}
        onChange={(showDrafts) => set({ showDrafts })}
      />
      <Toggle
        label="Reuse answers to repeated questions"
        hint="The same question with the same settings within a day gets its answer again at once (never for current events or answers from the web). Regenerate always asks afresh."
        checked={settings.cacheAnswers}
        onChange={(cacheAnswers) => set({ cacheAnswers })}
      />
      <h3 className="label mt-6 text-muted">Appearance</h3>
      <ThemeToggle />
      <Toggle
        label="High contrast"
        hint="Darker text, stronger borders and solid panels."
        checked={settings.highContrast}
        onChange={(highContrast) => set({ highContrast })}
      />
      <p className="mt-3 text-xs text-muted">
        Always shown: the council&apos;s agents as they work (with their times), the web results
        found, the searches the query planner ran, the knowledge-base excerpts each answer was
        given with their relevance scores,
        and for code reviews the analyser&apos;s full report.
      </p>
    </section>
  );
}

/** Dark (midnight glass) or light; kept in this browser, like the nav bar's switch. */
function ThemeToggle() {
  const [light, setLight] = useState(false);
  useEffect(() => setLight(currentTheme() === "light"), []);
  return (
    <Toggle
      label="Light theme"
      hint="The airy light look instead of midnight glass. The ☀ button in the top bar does the same."
      checked={light}
      onChange={(on) => {
        setLight(on);
        applyTheme(on ? "light" : "dark");
      }}
    />
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
