export interface CodeRange {
  file: string;
  startLine: number;
  endLine: number;
}

export interface ParsedCitation extends CodeRange {
  /** The citation as the model wrote it, which is how the API keys `citations[].ref`. */
  ref: string;
}

// A citation is `[path:42-58]` or `[path:42]`. Models also put several in one
// bracket, as `[path:5-7, 10-12]` or `[path:5-7, other/path:10-12]`; a range with
// no path belongs to the path before it. Keep in step with apps/api/app/services/search.py.
const BRACKET = /\[([^\[\]\n]+)\]/g;
const ITEM = /^\s*(?:([^\[\]:\n]+?)\s*:\s*)?(\d+)(?:\s*-\s*(\d+))?\s*$/;

interface CitationItem {
  file: string;
  start: string;
  end: string | undefined;
}

/** The items of a bracket, or null when it is not entirely citations (`[1, 2]`, link text). */
function parseBracket(content: string): CitationItem[] | null {
  const items: CitationItem[] = [];
  let file: string | null = null;
  for (const raw of content.split(/[,;]/)) {
    const match = ITEM.exec(raw);
    if (!match) return null;
    file = match[1] ? match[1].trim() : file;
    if (file === null) return null;
    items.push({ file, start: match[2], end: match[3] });
  }
  return items;
}
// Fenced blocks and inline code spans, which must be left untouched.
const CODE = /(```[\s\S]*?```|`[^`\n]*`)/g;
const HREF_PREFIX = "#cite:";

export function formatRange({ file, startLine, endLine }: CodeRange): string {
  return `${file}:${startLine}-${endLine}`;
}

function encodePath(file: string): string {
  // Parentheses would end a Markdown link target early.
  return encodeURIComponent(file).replace(/\(/g, "%28").replace(/\)/g, "%29");
}

/** Reads back a link produced by `linkifyCitations`; null for any other link. */
export function parseCitationHref(link: string | undefined): ParsedCitation | null {
  if (!link?.startsWith(HREF_PREFIX)) return null;
  const [path, start, end, form] = link.slice(HREF_PREFIX.length).split(":");
  const startLine = Number(start);
  const endLine = Number(end);
  if (!path || !Number.isInteger(startLine) || !Number.isInteger(endLine)) return null;
  const file = decodeURIComponent(path);
  const ref = form === "line" ? `[${file}:${startLine}]` : `[${file}:${startLine}-${endLine}]`;
  return { file, startLine, endLine, ref };
}

/**
 * Rewrites `[path:start-end]` citations in Markdown as links, so the renderer can
 * turn them into buttons. Citations inside code are left as written.
 */
export function linkifyCitations(markdown: string): string {
  return markdown
    .split(CODE)
    .map((part, index) => {
      if (index % 2 === 1) return part; // a code span or block
      return part.replace(BRACKET, (whole: string, content: string) => {
        const items = parseBracket(content);
        if (!items) return whole;
        // One link per item, so each place can be opened (and checked) on its own.
        return items
          .map(({ file, start, end }) => {
            const form = end ? "range" : "line";
            return `[source](${HREF_PREFIX}${encodePath(file)}:${start}:${end ?? start}:${form})`;
          })
          .join(" ");
      });
    })
    .join("");
}
