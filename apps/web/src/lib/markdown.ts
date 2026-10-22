// Fenced blocks and inline code spans, which must be left untouched.
const CODE = /(```[\s\S]*?```|`[^`\n]*`)/g;

/**
 * Maths in the forms models write it, as remark-math reads it: `\[…\]` and a line
 * that is only `$$…$$` become display blocks, `\(…\)` becomes inline `$…$`.
 */
export function normalizeMath(markdown: string): string {
  return markdown
    .split(CODE)
    .map((part, index) => {
      if (index % 2 === 1) return part; // code
      return part
        .replace(/\\\[([\s\S]+?)\\\]/g, (_m, tex: string) => `\n$$\n${tex.trim()}\n$$\n`)
        .replace(/\\\(([\s\S]+?)\\\)/g, (_m, tex: string) => `$${tex.trim()}$`)
        .replace(/^[ \t]*\$\$([^\n]+?)\$\$[ \t]*$/gm, (_m, tex: string) => `$$\n${tex.trim()}\n$$`);
    })
    .join("");
}
