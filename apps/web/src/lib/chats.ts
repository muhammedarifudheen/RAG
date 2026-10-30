import type {
  AnswerFormat,
  AnswerStyle,
  AskResponse,
  AssistantMode,
  Attachment,
} from "@atlas/shared";

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
  /** A preset role added before the custom instructions; "" is none. */
  persona: string;
  /** The longest answer in tokens; null is each model's default. */
  maxTokens: number | null;
  format: AnswerFormat;
  /** The AI services that may answer; empty is all of them. */
  services: string[];
  /** Agents answering in parallel; null is the server's choice (up to 12). */
  councilSize: number | null;
  /** The service to merge the drafts; "" picks the quickest. */
  merger: string;
  useSources: boolean;
  /** Knowledge-base excerpts per question. */
  topK: number;
  /** The relevance threshold for excerpts; null is the server's (0.3). */
  minScore: number | null;
  webSearch: boolean;
  /** Strict sources only: answers from the knowledge base alone, citing every claim. */
  strict: boolean;
  /** Deep research for every question (the composer's switch). */
  research: boolean;
  /** Deep research by itself for questions that look complex. */
  researchAuto: boolean;
  /** Reuse the answer to a question asked again within a day. */
  cacheAnswers: boolean;
  /** Stronger text and borders, solid panels. */
  highContrast: boolean;
  /** Plan several searches per question (keywords, a hypothetical answer, a variant). */
  planQueries: boolean;
  /** Fast models judge each excerpt's relevance; the best are kept, the weak left out. */
  rerank: boolean;
  /** Then one call ranks the kept excerpts together, best first. */
  rankPassages: boolean;
  /** The judge's cut-off, 0-10; null is the server's (4). */
  rerankCutoff: number | null;
  /** Show each agent's own draft under the merged answer. */
  showDrafts: boolean;
}

export const DEFAULT_SETTINGS: ChatSettings = {
  style: "balanced",
  temperature: null,
  instructions: "",
  speak: false,
  persona: "",
  maxTokens: null,
  format: "markdown",
  services: [],
  councilSize: null,
  merger: "",
  useSources: true,
  topK: 5,
  minScore: null,
  webSearch: true,
  strict: false,
  research: false,
  researchAuto: true,
  cacheAnswers: true,
  highContrast: false,
  planQueries: true,
  rerank: true,
  rankPassages: true,
  rerankCutoff: null,
  showDrafts: false,
};

/** Roles the assistant can take, sent before the user's own instructions. */
export const PERSONAS: { id: string; label: string; text: string }[] = [
  { id: "", label: "Default", text: "" },
  {
    id: "engineer",
    label: "Senior engineer",
    text: "Act as a senior software engineer: precise, pragmatic, with working code, edge cases and trade-offs.",
  },
  {
    id: "teacher",
    label: "Teacher",
    text: "Act as a patient teacher: explain step by step from first principles, with an example and a quick check of understanding.",
  },
  {
    id: "researcher",
    label: "Researcher",
    text: "Act as a careful researcher: separate established facts from claims, give dates and sources, and say what is uncertain.",
  },
  {
    id: "analyst",
    label: "Analyst",
    text: "Act as a business analyst: lead with the conclusion, quantify where possible, and use tables to compare options.",
  },
  {
    id: "writer",
    label: "Writer",
    text: "Act as a skilled writer and editor: clear, vivid and well structured prose, with a fitting tone.",
  },
];

/** Every AI service Atlas can use; which are active depends on the server's keys. */
export const AI_SERVICES: { id: string; label: string }[] = [
  { id: "gemini", label: "Gemini" },
  { id: "claude", label: "Claude" },
  { id: "groq", label: "Groq" },
  { id: "openrouter", label: "OpenRouter" },
  { id: "nvidia", label: "NVIDIA" },
  { id: "deepseek", label: "DeepSeek" },
  { id: "mistral", label: "Mistral" },
  { id: "cerebras", label: "Cerebras" },
  { id: "github", label: "GitHub Models" },
  { id: "cloudflare", label: "Cloudflare" },
  { id: "huggingface", label: "Hugging Face" },
  { id: "sambanova", label: "SambaNova" },
  { id: "cohere", label: "Cohere" },
  { id: "together", label: "Together" },
  { id: "pollinations", label: "Pollinations" },
  { id: "horde", label: "AI Horde" },
];

const CHATS_KEY = "atlas-chats";
const MODE_KEY = "atlas-mode";
const SETTINGS_KEY = "atlas-settings";
const ACTIVE_KEY = "atlas-active-services";
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

/**
 * The chat without the bytes of images: attached ones keep their names, and drawn
 * pictures that came as data (not a web address) are left out.
 */
export function withoutImageData(chat: SavedChat): SavedChat {
  return {
    ...chat,
    messages: chat.messages.map((message) => {
      if (message.role === "user" && message.attachments) {
        return {
          ...message,
          attachments: message.attachments.map(({ data: _data, ...rest }) => rest),
        };
      }
      if (message.role === "assistant" && message.response.images?.length) {
        const images = message.response.images.filter((image) => !image.url.startsWith("data:"));
        return { ...message, response: { ...message.response, images } };
      }
      return message;
    }),
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
    const stored = raw ? (JSON.parse(raw) as Partial<ChatSettings> & { version?: number }) : {};
    // Version 2: five excerpts by default, not eight; a saved 8 was the old default.
    if (!stored.version && stored.topK === 8) delete stored.topK;
    return { ...DEFAULT_SETTINGS, ...stored };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: ChatSettings): void {
  applyContrast(settings.highContrast);
  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify({ ...settings, version: 2 }));
  } catch {
    // Falls back to the defaults next time.
  }
}

/** Read by the script in the page head, so every page opens in the chosen contrast. */
export const CONTRAST_KEY = "atlas-contrast";

/** High contrast on or off for the whole site, and remembered for the next page. */
export function applyContrast(high: boolean): void {
  if (high) document.documentElement.dataset.contrast = "high";
  else delete document.documentElement.dataset.contrast;
  try {
    if (high) window.localStorage.setItem(CONTRAST_KEY, "high");
    else window.localStorage.removeItem(CONTRAST_KEY);
  } catch {
    // Applies to this page only.
  }
}

/** The services the server last said it can use (from an answer's route). */
export function loadActiveServices(): string[] {
  try {
    const raw = window.localStorage.getItem(ACTIVE_KEY);
    const active = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(active) ? active.filter((s): s is string => typeof s === "string") : [];
  } catch {
    return [];
  }
}

export function saveActiveServices(services: string[]): void {
  try {
    window.localStorage.setItem(ACTIVE_KEY, JSON.stringify(services));
  } catch {
    // Only a hint in the settings.
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
