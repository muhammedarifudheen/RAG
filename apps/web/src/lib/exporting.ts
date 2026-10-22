import type { SavedChat, StoredMessage } from "./chats";

/** A conversation as Markdown, for saving or pasting elsewhere. */
export function chatToMarkdown(title: string, messages: StoredMessage[]): string {
  const parts = [`# ${title}`, ""];
  for (const message of messages) {
    if (message.role === "user") {
      parts.push(`## You`, "", message.text);
      const files = message.attachments?.map((a) => a.name) ?? [];
      if (files.length) parts.push("", `_Attached: ${files.join(", ")}_`);
    } else if (message.role === "assistant") {
      const { response } = message;
      parts.push(`## Atlas`, "", response.answer);
      for (const image of response.images ?? []) parts.push("", `![${image.prompt}](${image.url})`);
      const sources = response.web_sources ?? [];
      if (sources.length) {
        parts.push("", "Sources:", ...sources.map((s) => `- [${s.title}](${s.url})`));
      }
    } else {
      parts.push(`> ${message.text}`);
    }
    parts.push("");
  }
  return parts.join("\n").trimEnd() + "\n";
}

/** Saves text as a file through the browser's download. */
export function download(filename: string, text: string, type = "text/plain"): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** A file name from a chat's title. */
export function fileNameOf(title: string, extension: string): string {
  const base = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return `${base || "atlas-chat"}.${extension}`;
}

export function exportAllChats(chats: SavedChat[]): void {
  const date = new Date().toISOString().slice(0, 10);
  download(`atlas-chats-${date}.json`, JSON.stringify(chats, null, 2), "application/json");
}

/** Copies text, falling back to a hidden text box where the clipboard API is missing. */
export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const box = document.createElement("textarea");
    box.value = text;
    box.style.position = "fixed";
    box.style.opacity = "0";
    document.body.appendChild(box);
    box.select();
    document.execCommand("copy");
    box.remove();
  }
}
