import type { AskResponse, AssistantMode } from "@atlas/shared";

/** A message as kept in a saved conversation. */
export type StoredMessage =
  | { role: "user"; text: string }
  | { role: "assistant"; response: AskResponse }
  | { role: "error"; text: string };

export interface SavedChat {
  id: string;
  title: string;
  updatedAt: number;
  messages: StoredMessage[];
}

const CHATS_KEY = "atlas-chats";
const MODE_KEY = "atlas-mode";
const MAX_CHATS = 50;

/**
 * Conversations are kept in this browser only (localStorage): private to the
 * visitor, and gone if they clear site data. Storage can be blocked or full;
 * then the chat still works, it just is not remembered.
 */
export function loadChats(): SavedChat[] {
  try {
    const raw = window.localStorage.getItem(CHATS_KEY);
    const chats = raw ? (JSON.parse(raw) as SavedChat[]) : [];
    return Array.isArray(chats) ? chats.filter((c) => c && Array.isArray(c.messages)) : [];
  } catch {
    return [];
  }
}

export function saveChats(chats: SavedChat[]): void {
  const newest = [...chats].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CHATS);
  try {
    window.localStorage.setItem(CHATS_KEY, JSON.stringify(newest));
  } catch {
    // Not remembered; the conversation on screen is unaffected.
  }
}

export function loadMode(): AssistantMode {
  try {
    return window.localStorage.getItem(MODE_KEY) === "best" ? "best" : "auto";
  } catch {
    return "auto";
  }
}

export function saveMode(mode: AssistantMode): void {
  try {
    window.localStorage.setItem(MODE_KEY, mode);
  } catch {
    // Falls back to the default next time.
  }
}

export function newChatId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** A conversation's name: its first question, shortened. */
export function titleOf(messages: StoredMessage[]): string {
  const first = messages.find((m) => m.role === "user");
  const text = first && first.role === "user" ? first.text.replace(/\s+/g, " ").trim() : "";
  if (!text) return "New chat";
  return text.length > 60 ? `${text.slice(0, 57)}…` : text;
}
