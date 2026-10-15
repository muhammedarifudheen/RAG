export interface CodeRange {
  file: string;
  startLine: number;
  endLine: number;
}

export interface ParsedCitation extends CodeRange {
  /** The citation as the model wrote it, which is how the API keys `citations[].ref`. */
  ref: string;
}

// `[path:42-58]`, `[path:42]`, and `[path:5-7, 10-12]` for several places in one file.
const CITATION = /\[([^\[\]:\n]+):(\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)*)\]/g;
const RANGE = /(\d+)(?:-(\d+))?/g;
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
      return part.replace(CITATION, (_match, path: string, ranges: string) => {
        const file = encodePath(path.trim());
        // One link per range, so each place can be opened (and checked) on its own.
        return [...ranges.matchAll(RANGE)]
          .map(([, start, end]) => {
            const form = end ? "range" : "line";
            return `[source](${HREF_PREFIX}${file}:${start}:${end ?? start}:${form})`;
          })
          .join(" ");
      });
    })
    .join("");
}
