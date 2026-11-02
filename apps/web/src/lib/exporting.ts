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

const CITATION = /\[([^\]\s]+:\d+(?:-\d+)?)\]/g;

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

/** A little Markdown as HTML, for printing: headings, lists, code, bold and code spans;
 * citations become numbered footnotes. */
function markdownToHtml(markdown: string, cite: (ref: string) => number): string {
  const out: string[] = [];
  const blocks = markdown.split(/```[^\n]*\n([\s\S]*?)```/);
  blocks.forEach((block, i) => {
    if (i % 2 === 1) {
      out.push(`<pre>${escapeHtml(block)}</pre>`);
      return;
    }
    for (const para of block.split(/\n{2,}/)) {
      const text = para.trim();
      if (!text) continue;
      const inline = (line: string) =>
        escapeHtml(line)
          .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
          .replace(/`([^`]+)`/g, "<code>$1</code>")
          .replace(CITATION, (_, ref: string) => `<sup>${cite(ref)}</sup>`);
      const heading = /^(#{1,4})\s+(.*)$/.exec(text);
      if (heading) {
        out.push(`<h${heading[1].length + 2}>${inline(heading[2])}</h${heading[1].length + 2}>`);
      } else if (text.split("\n").every((line) => /^\s*([-*]|\d+\.)\s/.test(line))) {
        const items = text.split("\n").map((line) => `<li>${inline(line.replace(/^\s*([-*]|\d+\.)\s+/, ""))}</li>`);
        out.push(`<ul>${items.join("")}</ul>`);
      } else {
        out.push(`<p>${text.split("\n").map(inline).join("<br>")}</p>`);
      }
    }
  });
  return out.join("\n");
}

/** A conversation as a printable page: each citation a numbered footnote. */
export function chatToHtml(title: string, messages: StoredMessage[]): string {
  const notes: string[] = [];
  const numbers = new Map<string, number>();
  const cite = (ref: string) => {
    if (!numbers.has(ref)) {
      notes.push(ref);
      numbers.set(ref, notes.length);
    }
    return numbers.get(ref)!;
  };
  const body: string[] = [`<h1>${escapeHtml(title)}</h1>`];
  for (const message of messages) {
    if (message.role === "user") {
      body.push(`<h2>You</h2><p>${escapeHtml(message.text).replace(/\n/g, "<br>")}</p>`);
    } else if (message.role === "assistant") {
      body.push(`<h2>Atlas</h2>${markdownToHtml(message.response.answer, cite)}`);
      if (message.response.footer) body.push(`<p class="footer">${escapeHtml(message.response.footer)}</p>`);
    }
  }
  const footnotes = notes.length
    ? `<h2>Sources</h2><ol class="notes">${notes.map((ref) => `<li>${escapeHtml(ref)}</li>`).join("")}</ol>`
    : "";
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title><style>
body{font:15px/1.55 Georgia,serif;max-width:46rem;margin:2rem auto;color:#111;padding:0 1rem}
h1{font-size:1.6rem}h2{font-size:1rem;margin-top:1.6rem;text-transform:uppercase;letter-spacing:.08em;color:#555}
pre,code{font-family:ui-monospace,monospace;font-size:.85em}pre{background:#f4f4f4;padding:.6rem;white-space:pre-wrap}
sup{color:#0645ad}.footer{font:12px ui-monospace,monospace;color:#666}.notes{font:12px ui-monospace,monospace}
</style></head><body>${body.join("\n")}${footnotes}</body></html>`;
}

/** Opens the conversation as a page to print or save as PDF. */
export function printChat(title: string, messages: StoredMessage[]): void {
  const view = window.open("", "_blank");
  if (!view) return;
  view.document.write(chatToHtml(title, messages));
  view.document.close();
  view.focus();
  setTimeout(() => view.print(), 300);
}
