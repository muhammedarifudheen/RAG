import type { AnswerStyle, AskResponse, AssistantMode, Attachment } from "@atlas/shared";

/** A file attached to a message. Images may lose `data` when storage runs short. */
export type StoredAttachment = Attachment & { size?: number; truncated?: boolean };

/** A message as kept in a saved conversation. `at` is when it was written (ms). */
export type StoredMessage =
  | { role: "user"; text: string; attachments?: StoredAttachment[]; at?: number }
  | { role: "assistant"; response: AskResponse; at?: number }
  | { role: "error"; text: string; at?: number };

export interface SavedChat {
  id: string;
  title: string;
  updatedAt: number;
  messages: StoredMessage[];
  pinned?: boolean;
  /** Set when the title was typed by the user, so it is not replaced. */
  renamed?: boolean;
}

/** What the visitor chose for every question; kept in this browser. */
export interface ChatSettings {
  style: AnswerStyle;
  /** Null: each model's own default. */
  temperature: number | null;
  instructions: string;
  /** Read each new answer aloud. */
  speak: boolean;
}

export const DEFAULT_SETTINGS: ChatSettings = {
  style: "balanced",
  temperature: null,
  instructions: "",
  speak: false,
};

const CHATS_KEY = "atlas-chats";
const MODE_KEY = "atlas-mode";
const SETTINGS_KEY = "atlas-settings";
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

/** Pinned chats first, then the most recently used. */
export function sortChats(chats: SavedChat[]): SavedChat[] {
  return [...chats].sort(
    (a, b) => Number(!!b.pinned) - Number(!!a.pinned) || b.updatedAt - a.updatedAt,
  );
}

export function saveChats(chats: SavedChat[]): void {
  const kept = [...chats].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CHATS);
  try {
    window.localStorage.setItem(CHATS_KEY, JSON.stringify(kept));
  } catch {
    // Most likely full: attached images are the bulk, so keep the chats without them.
    try {
      window.localStorage.setItem(CHATS_KEY, JSON.stringify(kept.map(withoutImageData)));
    } catch {
      // Not remembered; the conversation on screen is unaffected.
    }
  }
}

/** The chat without the bytes of attached images (their names stay). */
export function withoutImageData(chat: SavedChat): SavedChat {
  return {
    ...chat,
    messages: chat.messages.map((message) =>
      message.role === "user" && message.attachments
        ? {
            ...message,
            attachments: message.attachments.map(({ data: _data, ...rest }) => rest),
          }
        : message,
    ),
  };
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

export function loadSettings(): ChatSettings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    const stored = raw ? (JSON.parse(raw) as Partial<ChatSettings>) : {};
    return { ...DEFAULT_SETTINGS, ...stored };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: ChatSettings): void {
  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Falls back to the defaults next time.
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

/** Chats from an exported file, given fresh ids so they never overwrite existing ones. */
export function parseImportedChats(json: string): SavedChat[] {
  const data = JSON.parse(json) as unknown;
  const list = Array.isArray(data) ? data : [data];
  return list
    .filter(
      (c): c is SavedChat =>
        !!c && typeof c === "object" && Array.isArray((c as SavedChat).messages),
    )
    .map((c) => ({
      ...c,
      id: newChatId(),
      title: typeof c.title === "string" && c.title ? c.title : titleOf(c.messages),
      updatedAt: typeof c.updatedAt === "number" ? c.updatedAt : Date.now(),
    }));
}
