"use client";

import type { AskResponse } from "@atlas/shared";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { ask } from "@/lib/api";
import type { CodeRange } from "@/lib/citations";

import { Answer } from "./Answer";

// Loaded in the browser on first use. Next.js will not bundle Shiki for the server,
// which makes any module importing it asynchronous there and breaks server rendering
// of this page; it also keeps the highlighter out of the initial download.
const CodePanel = dynamic(() => import("./CodePanel").then((module) => module.CodePanel), {
  ssr: false,
});

type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; response: AskResponse }
  | { id: number; role: "error"; text: string };

// Omit applied to each member of the union separately, so `role` still discriminates.
type WithoutId<T> = T extends unknown ? Omit<T, "id"> : never;

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [selected, setSelected] = useState<CodeRange | null>(null);
  const nextId = useRef(0);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages, pending]);

  function add(message: WithoutId<Message>) {
    const id = nextId.current++;
    setMessages((current) => [...current, { ...message, id }]);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (!text || pending) return;

    add({ role: "user", text });
    setQuestion("");
    setPending(true);
    try {
      add({ role: "assistant", response: await ask({ question: text }) });
    } catch (error) {
      add({ role: "error", text: error instanceof Error ? error.message : "Request failed." });
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <div
          role="log"
          aria-label="Conversation"
          className="mx-auto w-full max-w-3xl flex-1 space-y-6 px-4 py-6"
        >
          {messages.length === 0 && (
            <div className="pt-16 text-center text-slate-500">
              <h1 className="text-xl font-semibold text-slate-800">Ask about the codebase</h1>
              <p className="mt-2 text-sm">
                Answers cite the code they are based on. Click a citation to read it.
              </p>
              <p className="mt-1 text-xs">
                Each question is answered on its own; earlier messages are not sent along.
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

          {pending && (
            <p role="status" className="animate-pulse text-sm text-slate-500">
              Searching the code and writing an answerâ€¦
            </p>
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
              placeholder="How are user names formatted?"
              autoComplete="off"
              maxLength={2000}
              className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200"
            />
            <button
              type="submit"
              disabled={pending || question.trim() === ""}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              Ask
            </button>
          </div>
        </form>
      </main>

      {selected && <CodePanel range={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
