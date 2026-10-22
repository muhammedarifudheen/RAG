"use client";

import type { AskResponse, GeneratedImage } from "@atlas/shared";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import {
  formatRange,
  linkifyCitations,
  parseCitationHref,
  type CodeRange,
} from "@/lib/citations";
import { copyText } from "@/lib/exporting";
import { normalizeMath } from "@/lib/markdown";

interface Props {
  response: AskResponse;
  onCite: (range: CodeRange) => void;
}

const REMARK = [remarkGfm, remarkMath];
const REHYPE = [rehypeKatex];

export function Answer({ response, onCite }: Props) {
  const markdown = useMemo(
    () => normalizeMath(linkifyCitations(response.answer)),
    [response.answer],
  );

  const components = useMemo<Components>(() => {
    const unverified = new Set(response.citations.filter((c) => !c.verified).map((c) => c.ref));
    return {
      pre: CodePre,
      a({ href, children }) {
        const citation = parseCitationHref(href);
        if (!citation) {
          return (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          );
        }
        const verified = !unverified.has(citation.ref);
        return (
          <button
            type="button"
            onClick={() => onCite(citation)}
            data-verified={verified}
            title={
              verified
                ? "Show this code"
                : "The model was not shown these lines, so this citation is unchecked"
            }
            className={`mx-0.5 border px-1.5 py-0.5 align-baseline font-mono text-[11px] transition-colors ${
              verified
                ? "border-cyan/40 bg-cyan/10 text-cyan hover:bg-cyan/20"
                : "border-warn/50 bg-warn/10 text-warn hover:bg-warn/20"
            }`}
          >
            {formatRange(citation)}
            {!verified && <span className="ml-1">(unverified)</span>}
          </button>
        );
      },
    };
  }, [response.citations, onCite]);

  return (
    <article aria-label="Answer" className="slab bg-panel/80 py-4 pl-5 pr-4">
      <div className="markdown text-[15px] leading-relaxed">
        <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={REHYPE} components={components}>
          {markdown}
        </ReactMarkdown>
      </div>

      {response.images && response.images.length > 0 && <Gallery images={response.images} />}

      {!response.complete && (
        <p className="mt-3 text-xs text-warn">This answer was cut off at the length limit.</p>
      )}

      {response.web_sources && response.web_sources.length > 0 && (
        <div className="mt-4 border-t border-line pt-3 text-xs">
          <p className="label text-muted">From the web</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {response.web_sources.map((source) => (
              <li key={source.url}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block max-w-[16rem] truncate border border-line px-2 py-1 text-cyan hover:border-cyan/60"
                >
                  {source.title}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {response.chunks.length > 0 && (
        <details className="mt-4 border-t border-line pt-3 text-xs text-soft">
          <summary className="cursor-pointer select-none text-muted hover:text-paper">
            {response.chunks.length} code excerpts were given to {response.model}
          </summary>
          <ul className="mt-2 space-y-1">
            {response.chunks.map((chunk) => (
              <li key={chunk.symbol_id}>
                <button
                  type="button"
                  onClick={() =>
                    onCite({
                      file: chunk.file,
                      startLine: chunk.start_line,
                      endLine: chunk.snippet_end_line,
                    })
                  }
                  className="text-left hover:text-cyan"
                >
                  <span className="font-mono">
                    {chunk.file}:{chunk.start_line}-{chunk.snippet_end_line}
                  </span>{" "}
                  <span className="text-muted">
                    {chunk.kind} {chunk.name} · {chunk.score.toFixed(2)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

/** An answer while it is being written: plain Markdown, citations not yet checked. */
export function StreamingAnswer({ text }: { text: string }) {
  return (
    <article aria-label="Writing the answer" aria-busy="true" className="slab bg-panel/80 py-4 pl-5 pr-4">
      <div className="markdown text-[15px] leading-relaxed">
        <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={REHYPE} components={{ pre: CodePre }}>
          {normalizeMath(text)}
        </ReactMarkdown>
      </div>
      <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-acid align-middle" />
    </article>
  );
}

/** Drawn pictures: one large, or several side by side. */
export function Gallery({ images }: { images: GeneratedImage[] }) {
  if (images.length === 1) {
    return (
      <div className="mt-4 max-w-md">
        <Picture image={images[0]} />
      </div>
    );
  }
  return (
    <ul aria-label="Pictures" className="mt-4 grid grid-cols-2 gap-3">
      {images.map((image, index) => (
        <li key={`${index}-${image.url.slice(0, 80)}`}>
          <Picture image={image} />
        </li>
      ))}
    </ul>
  );
}

/** A drawn picture: shown as it loads, with links to open and save it. */
function Picture({ image }: { image: GeneratedImage }) {
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  // Browsers will not open a data: URL in a new tab; such pictures can only be saved.
  const embedded = image.url.startsWith("data:");
  const extension = image.url.startsWith("data:image/webp") ? "webp" : "jpg";
  return (
    <figure>
      <div className="relative aspect-square w-full overflow-hidden border border-line bg-raised shadow-block">
        {state === "loading" && (
          <p className="label absolute inset-0 flex animate-pulse items-center justify-center text-muted">
            Drawing…
          </p>
        )}
        {state === "failed" && (
          <p className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-danger">
            The picture could not be drawn. The image service may be busy; try again.
          </p>
        )}
        {/* eslint-disable-next-line @next/next/no-img-element -- drawn elsewhere, any size */}
        <img
          src={image.url}
          alt={image.prompt}
          onLoad={() => setState("ready")}
          onError={() => setState("failed")}
          className={`h-full w-full object-cover transition-opacity ${state === "ready" ? "opacity-100" : "opacity-0"}`}
        />
      </div>
      <figcaption className="mt-2 flex flex-wrap items-center gap-3 text-xs">
        {image.service && <span className="label text-muted">{image.service}</span>}
        {!embedded && (
          <a href={image.url} target="_blank" rel="noreferrer" className="text-cyan hover:underline">
            Open full size
          </a>
        )}
        <a
          href={image.url}
          download={`atlas-picture.${extension}`}
          className="text-cyan hover:underline"
        >
          Download
        </a>
      </figcaption>
    </figure>
  );
}

interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: { className?: unknown };
  children?: HastNode[];
}

function textOf(node: HastNode | undefined): string {
  if (!node) return "";
  if (node.type === "text") return node.value ?? "";
  return (node.children ?? []).map(textOf).join("");
}

/** A fenced code block: highlighted once the language's grammar loads, with a copy button. */
function CodePre({ node, children }: { node?: unknown; children?: ReactNode }) {
  const code = (node as HastNode | undefined)?.children?.find((c) => c.tagName === "code");
  const classes = code?.properties?.className;
  const language =
    (Array.isArray(classes) ? classes : [])
      .map(String)
      .find((c) => c.startsWith("language-"))
      ?.slice("language-".length) ?? "";
  const text = textOf(code).replace(/\n$/, "");
  const [html, setHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setHtml(null);
    if (!language || text.length > 60_000) return;
    let current = true;
    // Loaded on demand, in the browser only (see CodePanel for why).
    void import("@/lib/highlight")
      .then(({ highlightSnippet }) => highlightSnippet(text, language))
      .then((result) => {
        if (current) setHtml(result);
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [text, language]);

  async function copy() {
    await copyText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="not-prose overflow-hidden border border-line bg-[#101010]">
      <div className="flex items-center justify-between border-b border-line bg-panel px-3 py-1">
        <span className="label text-muted">{language || "text"}</span>
        <button
          type="button"
          onClick={() => void copy()}
          className="label text-muted transition-colors hover:text-acid"
        >
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>
      {html ? (
        // Shiki escapes the code; the markup is its own token spans.
        <div className="[&_pre]:!m-0" dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <pre>{children}</pre>
      )}
    </div>
  );
}
