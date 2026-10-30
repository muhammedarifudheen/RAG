"use client";

import type {
  AskResponse,
  AssistantMode,
  AssistantRoute,
  ChatTurn,
  CodeAnalysis,
  CouncilAgent,
  GeneratedImage,
  ResearchStep,
  WebSource,
} from "@atlas/shared";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";

import { askAssistant, wakeServer } from "@/lib/api";
import { attachmentsToSend, imageSource } from "@/lib/attachments";
import {
  loadChats,
  loadMode,
  loadSettings,
  newChatId,
  parseImportedChats,
  saveChats,
  saveMode,
  saveActiveServices,
  saveSettings,
  titleOf,
  DEFAULT_SETTINGS,
  PERSONAS,
  type ChatSettings,
  type SavedChat,
  type StoredAttachment,
  type StoredMessage,
} from "@/lib/chats";
import type { CodeRange } from "@/lib/citations";
import { chatToMarkdown, copyText, download, exportAllChats, fileNameOf } from "@/lib/exporting";
import { useSpeaker } from "@/lib/speech";

import { Answer, Gallery, ResearchSteps, StreamingAnswer } from "./Answer";
import { ChatComposer, type ComposerHandle } from "./ChatComposer";
import { SettingsDialog, ShareDialog, ShortcutsDialog } from "./ChatDialogs";
import { ChatSidebar } from "./ChatSidebar";

// Loaded in the browser on first use. Next.js will not bundle Shiki for the server,
// which makes any module importing it asynchronous there and breaks server rendering
// of this page; it also keeps the highlighter out of the initial download.
const CodePanel = dynamic(() => import("./CodePanel").then((module) => module.CodePanel), {
  ssr: false,
});

type Message = StoredMessage & { id: number };

/** How many earlier messages go along with a question. */
const HISTORY_MESSAGES = 20;

const MODES: { value: AssistantMode; label: string; hint: string }[] = [
  { value: "auto", label: "Auto", hint: "Picks the best AI for each kind of question" },
  { value: "best", label: "Best model", hint: "Always starts with the strongest AI available" },
];

const STARTERS = [
  { tag: "Sources", text: "How does itsdangerous sign data and check a signature?" },
  { tag: "Picture", text: "Draw a retro-futurist city skyline at dusk, chrome and neon" },
  { tag: "Code", text: "Write a Python function that removes duplicates from a list, keeping order" },
  { tag: "Explain", text: "Explain the difference between TCP and UDP in a table" },
];

type DialogName = "settings" | "share" | "shortcuts" | null;

/** What the server has said about the answer being prepared. */
interface Progress {
  route: AssistantRoute | null;
  /** The code analyser's latest step, for a code review. */
  analysing: string | null;
  analysis: CodeAnalysis | null;
  searching: boolean;
  web: WebSource[] | null;
  agents: CouncilAgent[];
  merging: number | null;
  research: ResearchStep[];
  images: GeneratedImage[];
}

const NO_PROGRESS: Progress = {
  route: null,
  analysing: null,
  analysis: null,
  searching: false,
  web: null,
  agents: [],
  merging: null,
  research: [],
  images: [],
};

/** The chosen persona's role, then the user's own instructions. */
function withPersona(settings: ChatSettings): string {
  const persona = PERSONAS.find((p) => p.id === settings.persona)?.text ?? "";
  return [persona, settings.instructions.trim()].filter(Boolean).join("\n\n");
}

function turnsOf(messages: StoredMessage[]): ChatTurn[] {
  return messages
    .flatMap((message): ChatTurn[] => {
      if (message.role === "user") {
        const files = message.attachments?.map((a) => a.name) ?? [];
        const note = files.length ? `\n\n[Attached: ${files.join(", ")}]` : "";
        return [{ role: "user", content: message.text + note }];
      }
      if (message.role === "assistant") {
        return [{ role: "assistant", content: message.response.answer }];
      }
      return [];
    })
    .slice(-HISTORY_MESSAGES);
}

function timeOf(at: number | undefined): string {
  return at ? new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
}

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState<null | "answer" | "image">(null);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [progress, setProgress] = useState<Progress>(NO_PROGRESS);
  const [selected, setSelected] = useState<CodeRange | null>(null);
  const [chats, setChats] = useState<SavedChat[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [mode, setMode] = useState<AssistantMode>("auto");
  const [settings, setSettings] = useState<ChatSettings>(DEFAULT_SETTINGS);
  const [showChats, setShowChats] = useState(false);
  const [dialog, setDialog] = useState<DialogName>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const [atBottom, setAtBottom] = useState(true);
  const nextId = useRef(0);
  const log = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);
  const composer = useRef<ComposerHandle>(null);
  const search = useRef<HTMLInputElement>(null);
  const speaker = useSpeaker();

  const withIds = useCallback(
    (stored: StoredMessage[]): Message[] =>
      stored.map((message) => ({ ...message, id: nextId.current++ })),
    [],
  );

  // Saved chats and settings live in this browser; read them once mounted, and open
  // the chat named in the address (?c=…), as the share page does after an import.
  useEffect(() => {
    wakeServer();
    const saved = loadChats();
    setChats(saved);
    setMode(loadMode());
    setSettings(loadSettings());
    const wanted = new URLSearchParams(window.location.search).get("c");
    const chat = wanted ? saved.find((c) => c.id === wanted) : undefined;
    if (chat) {
      setChatId(chat.id);
      setMessages(withIds(chat.messages));
    }
  }, [withIds]);

  useEffect(() => {
    if (atBottom) end.current?.scrollIntoView({ block: "end" });
  }, [messages, pending, streaming, atBottom]);

  const flash = useCallback((text: string) => {
    setNotice(text);
    setTimeout(() => setNotice((current) => (current === text ? "" : current)), 1800);
  }, []);

  function remember(id: string, stored: StoredMessage[]) {
    setChats((current) => {
      const previous = current.find((c) => c.id === id);
      const chat: SavedChat = {
        ...previous,
        id,
        title: previous?.renamed ? previous.title : titleOf(stored),
        updatedAt: Date.now(),
        messages: stored,
      };
      const next = [chat, ...current.filter((c) => c.id !== id)];
      saveChats(next);
      return next;
    });
  }

  function updateChats(change: (chats: SavedChat[]) => SavedChat[]) {
    setChats((current) => {
      const next = change(current);
      saveChats(next);
      return next;
    });
  }

  /** Sends a question after `base`, the conversation so far (shorter when editing). */
  async function send(
    text: string,
    attachments: StoredAttachment[],
    draw: boolean,
    base: StoredMessage[] = messages.map(({ id: _id, ...message }) => message),
  ) {
    const trimmed = text.trim();
    if (!trimmed || pending) return;

    const id = chatId ?? newChatId();
    setChatId(id);
    setEditing(null);
    speaker.stop();
    const question: StoredMessage = {
      role: "user",
      text: trimmed,
      ...(attachments.length ? { attachments } : {}),
      at: Date.now(),
    };
    setMessages(withIds([...base, question]));
    setPending(draw ? "image" : "answer");
    setStreaming(null);
    setProgress(NO_PROGRESS);
    setAtBottom(true);
    const controller = new AbortController();
    abort.current = controller;

    let reply: StoredMessage;
    try {
      const response: AskResponse = await askAssistant(
        {
          question: trimmed,
          history: turnsOf(base),
          mode,
          attachments: attachmentsToSend(base, attachments),
          style: settings.style,
          temperature: settings.temperature,
          instructions: withPersona(settings),
          task: draw ? "image" : "answer",
          services: settings.services,
          councilSize: settings.councilSize,
          merger: settings.merger,
          useSources: settings.useSources,
          topK: settings.topK,
          minScore: settings.minScore,
          webSearch: settings.webSearch,
          maxTokens: settings.maxTokens,
          format: settings.format,
          includeDrafts: settings.showDrafts,
          strict: settings.strict,
          planQueries: settings.planQueries,
          research: settings.research ? true : settings.researchAuto ? undefined : false,
          rerank: settings.rerank,
          rankPassages: settings.rankPassages,
          rerankCutoff: settings.rerankCutoff,
        },
        {
          onDelta: (piece) => setStreaming((current) => (current ?? "") + piece),
          onReset: () => setStreaming(null),
          onRoute: (route, providers) => {
            setProgress((p) => ({ ...p, route }));
            // Every configured service is listed when none were chosen: remember them
            // so the settings can show which services this server has.
            if (!settings.services.length && providers.length) saveActiveServices(providers);
          },
          onAnalysing: (message) => setProgress((p) => ({ ...p, analysing: message })),
          onAnalysis: (analysis) => setProgress((p) => ({ ...p, analysis })),
          onSearching: () => setProgress((p) => ({ ...p, searching: true })),
          onWeb: (web) => setProgress((p) => ({ ...p, searching: false, web })),
          onAgent: (agent) =>
            setProgress((p) => {
              const known = p.agents.find((a) => a.id === agent.id);
              const agents = known
                ? p.agents.map((a) => (a.id === agent.id ? { ...a, ...agent } : a))
                : [...p.agents, agent];
              return { ...p, agents };
            }),
          onMerging: (drafts) => setProgress((p) => ({ ...p, merging: drafts })),
          onResearch: (step) => setProgress((p) => ({ ...p, research: [...p.research, step] })),
          onImage: (image) => setProgress((p) => ({ ...p, images: [...p.images, image] })),
        },
        controller.signal,
      );
      reply = { role: "assistant", response, at: Date.now() };
    } catch (error) {
      const stopped = error instanceof DOMException && error.name === "AbortError";
      reply = {
        role: "error",
        text: stopped
          ? "You stopped this answer."
          : error instanceof Error
            ? error.message
            : "Request failed.",
        at: Date.now(),
      };
    } finally {
      abort.current = null;
      setPending(null);
      setStreaming(null);
    }
    const [shown] = withIds([reply]);
    setMessages((current) => [...current, shown]);
    remember(id, [...base, question, reply]);
    if (reply.role === "assistant" && settings.speak) speaker.speak(`m-${shown.id}`, reply.response.answer);
  }

  /** Keeps a fact-check or gap report with its answer, so it is not asked for again. */
  function updateAnswer(messageId: number, checked: AskResponse, patch: Partial<AskResponse>) {
    const owner = chatId;
    setMessages((current) => {
      const at = current.findIndex(
        (m) =>
          m.id === messageId &&
          m.role === "assistant" &&
          m.response.answer === checked.answer &&
          m.response.question === checked.question,
      );
      if (at < 0) return current;
      const next = [...current];
      const message = next[at] as Extract<Message, { role: "assistant" }>;
      next[at] = {
        ...message,
        response: { ...message.response, ...patch },
      };
      if (owner) remember(owner, next.map(({ id: _id, ...rest }) => rest));
      return next;
    });
  }

  function stored(): StoredMessage[] {
    return messages.map(({ id: _id, ...message }) => message);
  }

  /** Asks the last question again (after an error, or for a different answer). */
  function regenerate() {
    const all = stored();
    const index = all.map((m) => m.role).lastIndexOf("user");
    if (index === -1) return;
    const question = all[index];
    if (question.role !== "user") return;
    const after = all[index + 1];
    const drew = after?.role === "assistant" && after.response.route === "image";
    void send(question.text, question.attachments ?? [], drew, all.slice(0, index));
  }

  function resendEdited(messageId: number, text: string) {
    const index = messages.findIndex((m) => m.id === messageId);
    const original = messages[index];
    if (index === -1 || original.role !== "user") return;
    void send(text, original.attachments ?? [], false, stored().slice(0, index));
  }

  function editLast() {
    const last = [...messages].reverse().find((m) => m.role === "user");
    if (last && !pending) setEditing(last.id);
  }

  function openChat(chat: SavedChat) {
    if (pending) return;
    speaker.stop();
    setChatId(chat.id);
    setMessages(withIds(chat.messages));
    setSelected(null);
    setEditing(null);
    setShowChats(false);
  }

  function startNewChat() {
    if (pending) return;
    speaker.stop();
    setChatId(null);
    setMessages([]);
    setSelected(null);
    setEditing(null);
    setShowChats(false);
    composer.current?.focus();
  }

  function deleteChat(id: string) {
    updateChats((current) => current.filter((c) => c.id !== id));
    if (id === chatId) startNewChat();
  }

  function chooseMode(next: AssistantMode) {
    setMode(next);
    saveMode(next);
  }

  function changeSettings(next: ChatSettings) {
    setSettings(next);
    saveSettings(next);
  }

  async function importChats(file: File) {
    try {
      const imported = parseImportedChats(await file.text());
      updateChats((current) => [...imported, ...current]);
      flash(`Imported ${imported.length} ${imported.length === 1 ? "chat" : "chats"}`);
    } catch {
      flash("That file is not an Atlas chats export");
    }
  }

  const copyAnswer = useCallback(
    async (text: string) => {
      await copyText(text);
      flash("Copied to the clipboard");
    },
    [flash],
  );

  const current = chats.find((c) => c.id === chatId) ?? null;
  const title = current?.title ?? (messages.length ? titleOf(stored()) : "New chat");

  // Keyboard shortcuts for the whole page; the message box handles Enter and ↑.
  const shortcuts = useRef<(event: KeyboardEvent) => void>(() => {});
  shortcuts.current = (event: KeyboardEvent) => {
    const mod = event.ctrlKey || event.metaKey;
    const typing =
      event.target instanceof HTMLElement &&
      (event.target.isContentEditable || ["INPUT", "TEXTAREA"].includes(event.target.tagName));
    if (event.key === "Escape" && pending && !dialog) {
      abort.current?.abort();
    } else if (mod && event.shiftKey && event.key.toLowerCase() === "o") {
      event.preventDefault();
      startNewChat();
    } else if (mod && !event.shiftKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      setShowChats(true);
      requestAnimationFrame(() => search.current?.focus());
    } else if (mod && event.key === "/") {
      event.preventDefault();
      setDialog("shortcuts");
    } else if (mod && event.shiftKey && event.key.toLowerCase() === "c") {
      const last = [...messages].reverse().find((m) => m.role === "assistant");
      if (last?.role === "assistant") {
        event.preventDefault();
        void copyAnswer(last.response.answer);
      }
    } else if (event.key === "/" && !typing && !mod && !dialog) {
      event.preventDefault();
      composer.current?.focus();
    }
  };
  useEffect(() => {
    const listener = (event: KeyboardEvent) => shortcuts.current(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  const drawing = pending === "image" || progress.route === "image";
  const last = messages.at(-1);
  const lastAnswerId = last?.role === "assistant" ? last.id : null;
  const suggestions = !pending && last?.role === "assistant" ? (last.response.suggestions ?? []) : [];

  return (
    // Exactly the screen below the navigation bar: only the conversation scrolls.
    <div className="relative flex h-[calc(100dvh-3.75rem)] min-h-0">
      <ChatSidebar
        ref={search}
        chats={chats}
        currentId={chatId}
        open={showChats}
        busy={pending !== null}
        onOpen={openChat}
        onNew={startNewChat}
        onDelete={deleteChat}
        onRename={(id, name) =>
          updateChats((all) => all.map((c) => (c.id === id ? { ...c, title: name, renamed: true } : c)))
        }
        onPin={(id) => updateChats((all) => all.map((c) => (c.id === id ? { ...c, pinned: !c.pinned } : c)))}
        onSettings={() => setDialog("settings")}
        onShortcuts={() => setDialog("shortcuts")}
      />
      {showChats && (
        <button
          type="button"
          aria-label="Close chats"
          onClick={() => setShowChats(false)}
          className="absolute inset-0 z-20 bg-black/60 md:hidden"
        />
      )}

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-white/70 bg-white/40 px-4 py-2 backdrop-blur-xl">
          <button
            type="button"
            onClick={() => setShowChats((v) => !v)}
            className="label border border-line px-2 py-1 text-muted md:hidden"
          >
            Chats
          </button>
          <p className="min-w-0 flex-1 truncate font-display text-sm font-medium text-soft">
            {title}
          </p>
          <div role="radiogroup" aria-label="Models" className="flex border border-line-strong">
            {MODES.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={mode === option.value}
                title={option.hint}
                onClick={() => chooseMode(option.value)}
                className={`whitespace-nowrap px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.1em] transition-colors ${
                  mode === option.value ? "bg-paper text-ink" : "text-muted hover:text-paper"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <HeaderButton
            label="Share"
            disabled={!current || pending !== null}
            onClick={() => setDialog("share")}
          />
          <HeaderButton
            label="Export"
            title="Save this chat as Markdown"
            disabled={messages.length === 0}
            onClick={() => download(fileNameOf(title, "md"), chatToMarkdown(title, stored()), "text/markdown")}
          />
        </div>

        <div
          ref={log}
          role="log"
          aria-label="Conversation"
          onScroll={(event) => {
            const box = event.currentTarget;
            setAtBottom(box.scrollHeight - box.scrollTop - box.clientHeight < 80);
          }}
          className="relative flex-1 overflow-y-auto"
        >
          <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6">
            {messages.length === 0 && <EmptyState onPick={(text) => void send(text, [], text.startsWith("Draw"))} />}

            {messages.map((message) => {
              if (message.role === "user") {
                return (
                  <UserMessage
                    key={message.id}
                    message={message}
                    editing={editing === message.id}
                    busy={pending !== null}
                    onEdit={() => setEditing(message.id)}
                    onCancel={() => setEditing(null)}
                    onResend={(text) => resendEdited(message.id, text)}
                    onCopy={() => void copyAnswer(message.text)}
                  />
                );
              }
              if (message.role === "error") {
                return (
                  <div key={message.id} className="space-y-2">
                    <p
                      role="alert"
                      className="border border-danger/40 bg-danger/10 p-3 text-sm text-danger"
                    >
                      {message.text}
                    </p>
                    {message.id === last?.id && !pending && (
                      <button
                        type="button"
                        onClick={regenerate}
                        className="label border border-line px-2.5 py-1 text-muted hover:border-line-strong hover:text-paper"
                      >
                        ↻ Try again
                      </button>
                    )}
                  </div>
                );
              }
              const speakingThis = speaker.speaking === `m-${message.id}`;
              return (
                <div key={message.id}>
                  <Answer
                    response={message.response}
                    onCite={setSelected}
                    onFactChecked={(report) =>
                      updateAnswer(message.id, message.response, {
                        fact_check: report,
                        fact_check_pending: false,
                      })
                    }
                    onGapsFound={(gaps) => updateAnswer(message.id, message.response, { gaps })}
                  />
                  <div className="mt-1.5 flex items-center gap-1 pl-1">
                    <ActionButton label="Copy answer" onClick={() => void copyAnswer(message.response.answer)}>
                      ⧉ Copy
                    </ActionButton>
                    {speaker.supported && (
                      <ActionButton
                        label="Read aloud"
                        pressed={speakingThis}
                        onClick={() =>
                          speakingThis
                            ? speaker.stop()
                            : speaker.speak(`m-${message.id}`, message.response.answer)
                        }
                      >
                        {speakingThis ? "■ Silence" : "▶ Listen"}
                      </ActionButton>
                    )}
                    {message.id === lastAnswerId && !pending && (
                      <ActionButton label="Regenerate" onClick={regenerate}>
                        ↻ Regenerate
                      </ActionButton>
                    )}
                    <span className="label ml-auto text-faint">{timeOf(message.at)}</span>
                  </div>
                </div>
              );
            })}

            {pending && streaming && !drawing && <StreamingAnswer text={streaming} />}

            {pending && (!streaming || drawing) && (
              <div role="status" className="slab py-2 pl-4 text-sm text-muted">
                <p className="animate-pulse">
                  {drawing
                    ? progress.images.length
                      ? `${progress.images.length} ${progress.images.length === 1 ? "picture" : "pictures"} ready, more on the way…`
                      : "Writing a description and drawing your picture…"
                    : progress.merging
                      ? `Merging the best points of ${progress.merging} answers…`
                      : progress.research.length && !progress.agents.length
                        ? `Researching: ${progress.research.length} of up to 6 steps…`
                      : progress.agents.length
                        ? `The council is answering: ${progress.agents.filter((a) => a.state === "done").length} of ${progress.agents.length} agents done…`
                        : progress.analysis
                          ? `Code analysed: grade ${progress.analysis.grade}, ${progress.analysis.counts.high} high and ${progress.analysis.counts.medium} medium findings. The council is reviewing…`
                          : progress.analysing
                            ? `${progress.analysing}…`
                            : progress.searching
                          ? "Searching the web for the latest information…"
                          : progress.web
                            ? `Read ${progress.web.length} web results; the council is starting…`
                            : "Searching the knowledge base and writing an answer…"}
                </p>
                {!drawing && progress.web && progress.web.length > 0 && (
                  <WebPanel sources={progress.web} />
                )}
                {!drawing && progress.research.length > 0 && <ResearchSteps steps={progress.research} />}
                {!drawing && progress.agents.length > 0 && <CouncilPanel agents={progress.agents} />}
                {drawing && progress.images.length > 0 && <Gallery images={progress.images} />}
              </div>
            )}

            {suggestions.length > 0 && (
              <div aria-label="Suggested questions" role="group" className="flex flex-wrap gap-2">
                {suggestions.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => void send(suggestion, [], false)}
                    className="border border-line px-3 py-1.5 text-left text-xs text-soft transition-colors before:mr-1.5 before:text-acid before:content-['→'] hover:border-acid hover:text-acid"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            )}
            <div ref={end} />
          </div>
        </div>

        {!atBottom && (
          <div className="pointer-events-none relative">
            <button
              type="button"
              onClick={() => {
                setAtBottom(true);
                end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
              }}
              className="label pointer-events-auto absolute -top-12 left-1/2 -translate-x-1/2 border border-line-strong bg-panel px-3 py-1.5 text-soft shadow-block-acid hover:text-paper"
            >
              ↓ Jump to latest
            </button>
          </div>
        )}

        <ChatComposer
          ref={composer}
          pending={pending !== null}
          onSend={(text, attachments, draw) => void send(text, attachments, draw)}
          strict={settings.strict}
          onStrict={(strict) => changeSettings({ ...settings, strict })}
          research={settings.research}
          onResearch={(research) => changeSettings({ ...settings, research })}
          onStop={() => abort.current?.abort()}
          onEditLast={editLast}
        />
        <p aria-live="polite" className="sr-only">
          {notice}
        </p>
        {notice && (
          <p className="label pointer-events-none fixed bottom-24 left-1/2 z-40 -translate-x-1/2 bg-acid px-3 py-1.5 text-ink">
            {notice}
          </p>
        )}
      </main>

      {selected && <CodePanel range={selected} onClose={() => setSelected(null)} />}

      {dialog === "settings" && (
        <SettingsDialog
          settings={settings}
          onChange={changeSettings}
          onClose={() => setDialog(null)}
          chatCount={chats.length}
          onExportAll={() => exportAllChats(chats)}
          onImport={(file) => void importChats(file)}
          onDeleteAll={() => {
            updateChats(() => []);
            startNewChat();
          }}
        />
      )}
      {dialog === "share" && current && <ShareDialog chat={current} onClose={() => setDialog(null)} />}
      {dialog === "shortcuts" && <ShortcutsDialog onClose={() => setDialog(null)} />}
    </div>
  );
}

const AGENT_STATES: Record<CouncilAgent["state"], { mark: string; tone: string; label: string }> = {
  thinking: { mark: "◌", tone: "border-line text-muted", label: "thinking" },
  done: { mark: "✓", tone: "border-ok/40 text-ok", label: "answered" },
  failed: { mark: "✕", tone: "border-danger/30 text-danger/80 line-through", label: "failed" },
  skipped: { mark: "…", tone: "border-line text-faint", label: "too slow" },
};

/** The council's agents and how each is getting on. */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Where the agents' fresh facts come from, while they answer. */
function WebPanel({ sources }: { sources: WebSource[] }) {
  return (
    <ul aria-label="Web results" className="mt-2 flex flex-wrap gap-1.5">
      {sources.slice(0, 8).map((source) => (
        <li key={source.url}>
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            title={source.title}
            className="inline-block max-w-[14rem] truncate border border-cyan/30 px-2 py-0.5 font-mono text-[10.5px] text-cyan hover:border-cyan/70"
          >
            {source.title.length > 48 ? `${source.title.slice(0, 47)}…` : source.title}
            <span className="ml-1 text-faint">{hostOf(source.url)}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

function CouncilPanel({ agents }: { agents: CouncilAgent[] }) {
  return (
    <ul aria-label="Council agents" className="mt-2 flex flex-wrap gap-1.5">
      {agents.map((agent) => {
        const look = AGENT_STATES[agent.state];
        return (
          <li
            key={agent.id}
            title={`${agent.service} ${agent.model}: ${look.label}${agent.seconds ? ` in ${agent.seconds}s` : ""}`}
            className={`flex items-center gap-1.5 border px-2 py-0.5 font-mono text-[10.5px] ${look.tone}`}
          >
            <span aria-hidden="true" className={agent.state === "thinking" ? "animate-spin" : ""}>
              {look.mark}
            </span>
            <span className="text-soft">{agent.service}</span>
            <span className="max-w-[10rem] truncate">{agent.model}</span>
            {agent.seconds != null && agent.state === "done" && (
              <span className="text-faint">{agent.seconds}s</span>
            )}
            <span className="sr-only">{look.label}</span>
          </li>
        );
      })}
    </ul>
  );
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="pt-6 sm:pt-12">
      <p className="label flex items-center gap-3 text-muted">
        <span className="bg-signal px-1.5 py-0.5 text-ink">02</span>
        Assistant
        <span aria-hidden="true" className="h-px flex-1 bg-line" />
      </p>
      <h1 className="mt-6 font-display text-3xl font-semibold leading-[1.08] tracking-tight sm:text-4xl">
        Ask about the codebase <span className="text-signal">—</span>{" "}
        <span className="chrome-text">or anything else</span>
      </h1>
      <p className="mt-4 max-w-xl text-sm text-soft">
        Atlas answers from your sources first, citing the exact lines, then from the web and
        general knowledge. Attach PDFs, code or images, have it draw a picture, and follow up:
        it remembers the conversation.
      </p>
      <ul className="mt-8 grid gap-3 sm:grid-cols-2">
        {STARTERS.map((starter, index) => (
          <li key={starter.text}>
            <button
              type="button"
              onClick={() => onPick(starter.text)}
              className="glass group flex h-full w-full flex-col gap-2 rounded-glass p-4 text-left shadow-block transition-all hover:-translate-y-1 hover:shadow-float"
            >
              <span className="label flex items-center gap-2 text-muted">
                <span className="text-signal">{String(index + 1).padStart(2, "0")}</span>
                {starter.tag}
              </span>
              <span className="text-sm text-soft group-hover:text-paper">{starter.text}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function UserMessage({
  message,
  editing,
  busy,
  onEdit,
  onCancel,
  onResend,
  onCopy,
}: {
  message: Extract<StoredMessage, { role: "user" }> & { id: number };
  editing: boolean;
  busy: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onResend: (text: string) => void;
  onCopy: () => void;
}) {
  const [draft, setDraft] = useState(message.text);
  useEffect(() => {
    if (editing) setDraft(message.text);
  }, [editing, message.text]);

  return (
    <div className="group flex flex-col items-end">
      {message.attachments && message.attachments.length > 0 && (
        <ul className="mb-1.5 flex max-w-[85%] flex-wrap justify-end gap-1.5">
          {message.attachments.map((attachment, index) => {
            const source = imageSource(attachment);
            return (
              <li key={`${attachment.name}-${index}`} className="border border-line bg-panel text-xs text-soft">
                {source ? (
                  // eslint-disable-next-line @next/next/no-img-element -- the user's own image
                  <img src={source} alt={attachment.name} className="h-24 max-w-[12rem] object-cover" />
                ) : (
                  <span className="flex items-center gap-1.5 px-2 py-1">
                    <span className="font-mono text-[10px] text-acid">
                      {attachment.kind === "image" ? "IMG" : "TXT"}
                    </span>
                    {attachment.name}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {editing ? (
        <form
          className="w-full max-w-[85%]"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.trim()) onResend(draft);
          }}
        >
          <textarea
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") onCancel();
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (draft.trim()) onResend(draft);
              }
            }}
            aria-label="Edit your message"
            rows={Math.min(8, draft.split("\n").length + 1)}
            className="w-full resize-y border border-signal bg-panel px-3 py-2 text-sm outline-none"
          />
          <div className="mt-1.5 flex justify-end gap-2">
            <button type="button" onClick={onCancel} className="label px-2 py-1 text-muted hover:text-paper">
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy || !draft.trim()}
              className="label bg-signal px-3 py-1 text-ink hover:bg-signal-hover disabled:opacity-50"
            >
              Send edit
            </button>
          </div>
        </form>
      ) : (
        <>
          <p className="max-w-[85%] whitespace-pre-wrap rounded-[20px] rounded-br-md bg-paper px-4 py-2.5 text-[15px] text-ink shadow-float">
            {message.text}
          </p>
          <div className="mt-1 flex items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
            <span className="label mr-1 text-faint">{timeOf(message.at)}</span>
            <ActionButton label="Copy message" onClick={onCopy}>
              ⧉
            </ActionButton>
            {!busy && (
              <ActionButton label="Edit message" onClick={onEdit}>
                ✎ Edit
              </ActionButton>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function ActionButton({
  label,
  pressed,
  onClick,
  children,
}: {
  label: string;
  pressed?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      className={`label px-2 py-1 transition-colors ${pressed ? "text-acid" : "text-muted hover:text-paper"}`}
    >
      {children}
    </button>
  );
}

function HeaderButton({
  label,
  title,
  disabled,
  onClick,
}: {
  label: string;
  title?: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title ?? label}
      className="label border border-line px-2 py-1.5 text-muted transition-colors hover:border-line-strong hover:text-paper disabled:opacity-40 sm:px-2.5"
    >
      {label}
    </button>
  );
}
