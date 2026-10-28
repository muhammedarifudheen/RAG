"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getShare } from "@/lib/api";
import { loadChats, newChatId, saveChats, type StoredMessage } from "@/lib/chats";
import type { CodeRange } from "@/lib/citations";

import { Answer } from "./Answer";
import { ErrorMessage, Loading } from "./States";

// In the browser only, as on the chat page.
const CodePanel = dynamic(() => import("./CodePanel").then((module) => module.CodePanel), {
  ssr: false,
});

type Shared = { title: string; messages: StoredMessage[]; created_at: string };

/** A chat someone shared by link: read-only, with a way to carry it on as one's own. */
export function SharedChatView() {
  const router = useRouter();
  const [state, setState] = useState<
    { status: "loading" } | { status: "ready"; chat: Shared } | { status: "error"; message: string }
  >({ status: "loading" });
  const [selected, setSelected] = useState<CodeRange | null>(null);

  useEffect(() => {
    // Read from the address in the browser: the page is static, the id is not.
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) {
      setState({ status: "error", message: "This link does not name a shared chat." });
      return;
    }
    getShare<StoredMessage>(id)
      .then((chat) => setState({ status: "ready", chat }))
      .catch((error: unknown) =>
        setState({
          status: "error",
          message: error instanceof Error ? error.message : "The shared chat could not be loaded.",
        }),
      );
  }, []);

  function continueChat(chat: Shared) {
    const id = newChatId();
    saveChats([{ id, title: chat.title, updatedAt: Date.now(), messages: chat.messages }, ...loadChats()]);
    router.push(`/chat?c=${encodeURIComponent(id)}`);
  }

  if (state.status === "loading") return <Loading label="Loading the shared chat…" />;
  if (state.status === "error") return <ErrorMessage message={state.message} />;

  const { chat } = state;
  return (
    <div className="flex min-h-0 flex-1">
      <main className="mx-auto w-full max-w-3xl px-4 py-10">
        <p className="label flex items-center gap-3 text-muted">
          <span className="bg-signal px-1.5 py-0.5 text-ink">Shared</span>
          {new Date(chat.created_at).toLocaleDateString(undefined, { dateStyle: "medium" })}
          <span aria-hidden="true" className="h-px flex-1 bg-line" />
        </p>
        <h1 className="mt-5 font-display text-2xl font-semibold leading-tight tracking-tight">
          {chat.title}
        </h1>
        <div className="mt-4 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => continueChat(chat)}
            className="bg-signal px-4 py-2 font-display text-xs font-bold uppercase tracking-[0.14em] text-ink hover:bg-signal-hover"
          >
            Continue this chat
          </button>
          <Link href="/chat" className="label border border-line px-4 py-2 text-muted hover:text-paper">
            Start your own
          </Link>
        </div>

        <div role="log" aria-label="Shared conversation" className="mt-8 space-y-6">
          {chat.messages.map((message, index) => {
            if (message.role === "user") {
              return (
                <div key={index} className="flex flex-col items-end">
                  {message.attachments?.length ? (
                    <p className="label mb-1 text-faint">
                      Attached: {message.attachments.map((a) => a.name).join(", ")}
                    </p>
                  ) : null}
                  <p className="max-w-[85%] whitespace-pre-wrap border border-line-strong bg-raised px-4 py-2.5 text-[15px]">
                    {message.text}
                  </p>
                </div>
              );
            }
            if (message.role === "error") {
              return (
                <p key={index} className="border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
                  {message.text}
                </p>
              );
            }
            return <Answer key={index} response={message.response} onCite={setSelected} />;
          })}
        </div>
      </main>
      {selected && <CodePanel range={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
