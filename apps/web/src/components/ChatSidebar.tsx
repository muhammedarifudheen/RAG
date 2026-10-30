"use client";

import { forwardRef, useState, type FormEvent } from "react";

import { sortChats, type SavedChat } from "@/lib/chats";

interface Props {
  chats: SavedChat[];
  currentId: string | null;
  open: boolean;
  /** Folded away on wide screens (the header's toggle). */
  collapsed?: boolean;
  busy: boolean;
  onOpen: (chat: SavedChat) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onPin: (id: string) => void;
  onSettings: () => void;
  onShortcuts: () => void;
}

/** The saved chats, pinned first: search, open, rename, pin and delete. */
export const ChatSidebar = forwardRef<HTMLInputElement, Props>(function ChatSidebar(
  {
    chats,
    currentId,
    open,
    collapsed = false,
    busy,
    onOpen,
    onNew,
    onDelete,
    onRename,
    onPin,
    onSettings,
    onShortcuts,
  },
  searchRef,
) {
  const [filter, setFilter] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const needle = filter.trim().toLowerCase();
  const shown = sortChats(chats).filter(
    (chat) =>
      !needle ||
      chat.title.toLowerCase().includes(needle) ||
      chat.messages.some(
        (m) =>
          (m.role === "user" && m.text.toLowerCase().includes(needle)) ||
          (m.role === "assistant" && m.response.answer.toLowerCase().includes(needle)),
      ),
  );

  function finishRename(event: FormEvent, id: string) {
    event.preventDefault();
    if (draft.trim()) onRename(id, draft.trim().slice(0, 80));
    setRenaming(null);
  }

  return (
    <aside
      aria-label="Saved chats"
      className={`${open ? "flex" : "hidden"} absolute inset-y-0 left-0 z-30 w-72 shrink-0 flex-col border-r border-line/50 bg-panel/70 backdrop-blur-xl md:static md:w-60 ${collapsed ? "md:hidden" : "md:flex"}`}
    >
      <div className="space-y-2 p-3">
        <button
          type="button"
          onClick={onNew}
          disabled={busy}
          className="w-full rounded-full bg-signal px-4 py-2 text-left font-display text-[13px] font-medium text-white shadow-glow transition-colors hover:bg-signal-hover disabled:opacity-50"
        >
          + New chat
        </button>
        <input
          ref={searchRef}
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Search chats"
          aria-label="Search chats"
          className="w-full border border-line bg-panel px-2.5 py-1.5 text-sm outline-none placeholder:text-faint focus:border-line-strong"
        />
      </div>

      <p className="label px-4 pb-1 text-faint">
        {chats.length === 0 ? "No chats yet" : needle ? `${shown.length} found` : "History"}
      </p>
      <ul className="min-h-0 flex-1 space-y-px overflow-y-auto px-2 pb-3">
        {chats.length === 0 && (
          <li className="px-2 py-1 text-xs text-muted">Your chats are kept in this browser.</li>
        )}
        {shown.map((chat) => (
          <li key={chat.id} className="group relative flex items-center">
            {renaming === chat.id ? (
              <form onSubmit={(event) => finishRename(event, chat.id)} className="flex-1">
                <input
                  autoFocus
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onBlur={(event) => finishRename(event, chat.id)}
                  onKeyDown={(event) => event.key === "Escape" && setRenaming(null)}
                  aria-label="New chat name"
                  className="w-full border border-signal bg-panel px-2 py-1.5 text-sm outline-none"
                />
              </form>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => onOpen(chat)}
                  aria-current={chat.id === currentId ? "page" : undefined}
                  className={`min-w-0 flex-1 truncate border-l-2 px-2 py-1.5 text-left text-sm transition-colors ${
                    chat.id === currentId
                      ? "border-signal bg-raised text-paper"
                      : "border-transparent text-soft hover:bg-panel hover:text-paper"
                  }`}
                >
                  {chat.pinned && (
                    <span aria-hidden="true" className="mr-1 text-acid">
                      ✦
                    </span>
                  )}
                  {chat.title}
                </button>
                <span className="absolute right-0 flex items-center bg-raised opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                  <IconButton
                    label={`${chat.pinned ? "Unpin" : "Pin"} chat ${chat.title}`}
                    onClick={() => onPin(chat.id)}
                  >
                    {chat.pinned ? "◆" : "◇"}
                  </IconButton>
                  <IconButton
                    label={`Rename chat ${chat.title}`}
                    onClick={() => {
                      setDraft(chat.title);
                      setRenaming(chat.id);
                    }}
                  >
                    ✎
                  </IconButton>
                  <IconButton label={`Delete chat ${chat.title}`} onClick={() => onDelete(chat.id)} danger>
                    ✕
                  </IconButton>
                </span>
              </>
            )}
          </li>
        ))}
      </ul>

      <div className="flex border-t border-line">
        <button
          type="button"
          onClick={onSettings}
          className="label flex-1 px-3 py-3 text-left text-muted hover:bg-panel hover:text-paper"
        >
          ⚙ Settings
        </button>
        <button
          type="button"
          onClick={onShortcuts}
          aria-label="Keyboard shortcuts"
          className="label border-l border-line px-3 py-3 text-muted hover:bg-panel hover:text-paper"
        >
          ⌘ Keys
        </button>
      </div>
    </aside>
  );
});

function IconButton({
  label,
  onClick,
  danger = false,
  children,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label.split(" chat ")[0]}
      className={`px-1.5 py-1.5 text-xs text-muted transition-colors ${danger ? "hover:text-danger" : "hover:text-acid"}`}
    >
      {children}
    </button>
  );
}
