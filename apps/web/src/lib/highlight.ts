import { createHighlighterCore, type HighlighterCore } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";

const THEME = "vesper";
const LANGUAGES = ["python", "typescript", "tsx", "go"];

let highlighter: Promise<HighlighterCore> | null = null;

function load(): Promise<HighlighterCore> {
  // Only the grammars the ingestion worker can parse, and the JavaScript regex
  // engine so no WASM file has to be served.
  highlighter ??= createHighlighterCore({
    themes: [import("shiki/themes/vesper.mjs")],
    langs: [
      import("shiki/langs/python.mjs"),
      import("shiki/langs/typescript.mjs"),
      import("shiki/langs/tsx.mjs"),
      import("shiki/langs/go.mjs"),
    ],
    engine: createJavaScriptRegexEngine(),
  });
  return highlighter;
}

export function shikiLanguage(path: string, language: string): string {
  if (path.endsWith(".tsx")) return "tsx";
  return LANGUAGES.includes(language) ? language : "text";
}

/**
 * Highlights a whole file. Every line gets a `data-line` attribute, and lines
 * within the given range also get the `cited` class.
 */
export async function highlightCode(
  code: string,
  language: string,
  cited: { startLine: number; endLine: number },
): Promise<string> {
  const shiki = await load();
  return shiki.codeToHtml(code, {
    lang: language,
    theme: THEME,
    transformers: [
      {
        line(node, line) {
          node.properties["data-line"] = line;
          if (line >= cited.startLine && line <= cited.endLine) {
            this.addClassToHast(node, "cited");
          }
        },
      },
    ],
  });
}

/** Language names models write after ``` that Shiki knows by another name. */
const ALIASES: Record<string, string> = { sh: "bash", shell: "bash", zsh: "bash", py: "python" };

/**
 * Highlights a code block from an answer, loading its language on first use.
 * Null for a language Shiki does not know, which is then shown plain.
 */
export async function highlightSnippet(code: string, language: string): Promise<string | null> {
  const { bundledLanguages } = await import("shiki/langs");
  const id = ALIASES[language.toLowerCase()] ?? language.toLowerCase();
  const grammar = bundledLanguages[id as keyof typeof bundledLanguages];
  if (!grammar) return null;
  const shiki = await load();
  try {
    if (!shiki.getLoadedLanguages().includes(id)) await shiki.loadLanguage(grammar);
    return shiki.codeToHtml(code, { lang: id, theme: THEME });
  } catch {
    return null; // a grammar the JavaScript regex engine cannot run
  }
}
