"use client";

import type { AskResponse, AssistantMode, ChatTurn } from "@atlas/shared";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { askAssistant } from "@/lib/api";
import {
  loadChats,
  loadMode,
  newChatId,
  saveChats,
  saveMode,
  titleOf,
  type SavedChat,
  type StoredMessage,
} from "@/lib/chats";
import type { CodeRange } from "@/lib/citations";

import { Answer, StreamingAnswer } from "./Answer";
import { useTakingLong, WAKING_HINT } from "./States";

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

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [streaming, setStreaming] = useState<string | null>(null);
  const slow = useTakingLong(pending && !streaming);
  const [selected, setSelected] = useState<CodeRange | null>(null);
  const [chats, setChats] = useState<SavedChat[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [mode, setMode] = useState<AssistantMode>("auto");
  const [showChats, setShowChats] = useState(false);
  const nextId = useRef(0);
  const end = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);

  // Saved chats and the mode live in this browser; read them once mounted.
  useEffect(() => {
    setChats(loadChats());
    setMode(loadMode());
  }, []);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages, pending, streaming]);

  const withIds = useCallback(
    (stored: StoredMessage[]): Message[] =>
      stored.map((message) => ({ ...message, id: nextId.current++ })),
    [],
  );

  function remember(id: string, stored: StoredMessage[]) {
    setChats((current) => {
      const chat: SavedChat = { id, title: titleOf(stored), updatedAt: Date.now(), messages: stored };
      const next = [chat, ...current.filter((c) => c.id !== id)];
      saveChats(next);
      return next;
    });
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || pending) return;

    const id = chatId ?? newChatId();
    setChatId(id);
    const before: StoredMessage[] = messages.map(({ id: _id, ...message }) => message);
    const history: ChatTurn[] = before
      .flatMap((message): ChatTurn[] => {
        if (message.role === "user") return [{ role: "user", content: message.text }];
        if (message.role === "assistant") {
          return [{ role: "assistant", content: message.response.answer }];
        }
        return [];
      })
      .slice(-HISTORY_MESSAGES);

    setMessages((current) => [...current, ...withIds([{ role: "user", text: trimmed }])]);
    setQuestion("");
    setPending(true);
    setStreaming(null);
    const controller = new AbortController();
    abort.current = controller;

    let reply: StoredMessage;
    try {
      const response: AskResponse = await askAssistant(
        trimmed,
        history,
        mode,
        {
          onDelta: (piece) => setStreaming((current) => (current ?? "") + piece),
          onReset: () => setStreaming(null),
        },
        controller.signal,
      );
      reply = { role: "assistant", response };
    } catch (error) {
      const stopped = error instanceof DOMException && error.name === "AbortError";
      reply = {
        role: "error",
        text: stopped
          ? "You stopped this answer."
          : error instanceof Error
            ? error.message
            : "Request failed.",
      };
    } finally {
      abort.current = null;
      setPending(false);
      setStreaming(null);
    }
    setMessages((current) => [...current, ...withIds([reply])]);
    remember(id, [...before, { role: "user", text: trimmed }, reply]);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send(question);
  }

  function openChat(chat: SavedChat) {
    if (pending) return;
    setChatId(chat.id);
    setMessages(withIds(chat.messages));
    setSelected(null);
    setShowChats(false);
  }

  function startNewChat() {
    if (pending) return;
    setChatId(null);
    setMessages([]);
    setSelected(null);
    setShowChats(false);
  }

  function deleteChat(id: string) {
    setChats((current) => {
      const next = current.filter((c) => c.id !== id);
      saveChats(next);
      return next;
    });
    if (id === chatId) startNewChat();
  }

  function chooseMode(next: AssistantMode) {
    setMode(next);
    saveMode(next);
  }

  const last = messages.at(-1);
  const suggestions =
    !pending && last?.role === "assistant" ? (last.response.suggestions ?? []) : [];

  return (
    <div className="flex min-h-0 flex-1">
      <aside
        aria-label="Saved chats"
        className={`${showChats ? "flex" : "hidden"} w-64 shrink-0 flex-col border-r border-slate-200 bg-slate-50 md:flex`}
      >
        <div className="p-3">
          <button
            type="button"
            onClick={startNewChat}
            disabled={pending}
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
          >
            + New chat
          </button>
        </div>
        <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
          {chats.length === 0 && (
            <li className="px-2 py-1 text-xs text-slate-500">Your chats are kept in this browser.</li>
          )}
          {chats.map((chat) => (
            <li key={chat.id} className="group flex items-center gap-1">
              <button
                type="button"
                onClick={() => openChat(chat)}
                aria-current={chat.id === chatId ? "page" : undefined}
                className={`min-w-0 flex-1 truncate rounded px-2 py-1.5 text-left text-sm ${
                  chat.id === chatId
                    ? "bg-indigo-100 text-indigo-900"
                    : "text-slate-700 hover:bg-slate-200"
                }`}
              >
                {chat.title}
              </button>
              <button
                type="button"
                onClick={() => deleteChat(chat.id)}
                aria-label={`Delete chat ${chat.title}`}
                className="rounded px-1.5 py-1 text-xs text-slate-400 opacity-0 hover:bg-slate-200 hover:text-red-700 focus:opacity-100 group-hover:opacity-100"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-2">
          <button
            type="button"
            onClick={() => setShowChats((v) => !v)}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 md:hidden"
          >
            Chats
          </button>
          <div role="radiogroup" aria-label="Models" className="ml-auto flex rounded-md border border-slate-300 p-0.5">
            {MODES.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={mode === option.value}
                title={option.hint}
                onClick={() => chooseMode(option.value)}
                className={`rounded px-2.5 py-1 text-xs font-medium ${
                  mode === option.value ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div
          role="log"
          aria-label="Conversation"
          className="mx-auto w-full max-w-3xl flex-1 space-y-6 overflow-y-auto px-4 py-6"
        >
          {messages.length === 0 && (
            <div className="pt-16 text-center text-slate-500">
              <h1 className="text-xl font-semibold text-slate-800">
                Ask about the codebase — or anything else
              </h1>
              <p className="mt-2 text-sm">
                Atlas answers from your sources first, citing the exact lines, then from the
                web and general knowledge. Follow-up questions remember the conversation.
              </p>
            </div>
          )}

          {messages.map((message) => {
            if (message.role === "user") {
              return (
                <div key={message.id} className="flex justify-end">
                  <p className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-indigo-600 px-4 py-2 text-sm text-white">
                    {message.text}
                  </p>
                </div>
              );
            }
            if (message.role === "error") {
              return (
                <p
                  key={message.id}
                  role="alert"
                  className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
                >
                  {message.text}
                </p>
              );
            }
            return <Answer key={message.id} response={message.response} onCite={setSelected} />;
          })}

          {pending && streaming && <StreamingAnswer text={streaming} />}

          {pending && !streaming && (
            <div role="status" className="text-sm text-slate-500">
              <p className="animate-pulse">Searching the knowledge base and writing an answer…</p>
              {slow && <p className="mt-1">{WAKING_HINT}</p>}
            </div>
          )}

          {suggestions.length > 0 && (
            <div aria-label="Suggested questions" role="group" className="flex flex-wrap gap-2">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => void send(suggestion)}
                  className="rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-left text-xs text-indigo-800 hover:bg-indigo-100"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}
          <div ref={end} />
        </div>

        <form
          onSubmit={onSubmit}
          className="sticky bottom-0 border-t border-slate-200 bg-white px-4 py-3"
        >
          <div className="mx-auto flex max-w-3xl gap-2">
            <label htmlFor="question" className="sr-only">
              Question
            </label>
            <input
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask anything…"
              autoComplete="off"
              maxLength={2000}
              className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200"
            />
            {pending ? (
              <button
                type="button"
                onClick={() => abort.current?.abort()}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
              >
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={question.trim() === ""}
                className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                Ask
              </button>
            )}
          </div>
        </form>
      </main>

      {selected && <CodePanel range={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
