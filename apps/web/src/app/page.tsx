import Link from "next/link";

import { IngestForm } from "@/components/IngestForm";
import { Dragon, GlassCards, PearlRule, type Feature } from "@/components/Ornament";

// What Atlas reads, each card lit by one of the dragon's colours.
const FEATURES: Feature[] = [
  {
    title: "Repositories",
    text: "GitHub code, mapped to its functions, classes and the calls between them.",
    scale: "violet",
  },
  {
    title: "Web & Wikipedia",
    text: "Pages, whole sites and articles, each credited with its licence.",
    scale: "turquoise",
  },
  {
    title: "Documents",
    text: "PDF, EPUB, Word, Markdown and text, split where their sections do.",
    scale: "magenta",
  },
  {
    title: "Code files",
    text: "Python, TypeScript and Go, parsed like a repository of one.",
    scale: "jade",
  },
];

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8">
      {/* The heading, with the glass dragon coiled through it. */}
      <div className="hero relative mx-auto max-w-2xl px-4 pb-14 pt-28 text-center sm:pt-32">
        <Dragon className="absolute left-1/2 top-0 h-full w-full -translate-x-1/2 sm:w-[128%]" />
        <p className="label relative flex items-center justify-center gap-3 text-muted">
          <span className="bg-signal px-1.5 py-0.5 text-on-signal">01</span>
          Sources
        </p>
        <h1 className="relative mt-5 font-display text-4xl font-semibold leading-[1.02] tracking-tight sm:text-6xl">
          Build a <span className="chrome-text italic">knowledge</span> base
        </h1>
        <PearlRule className="relative mx-auto mt-6 max-w-xs" />
        <p className="label relative mt-5 text-signal">
          Grounded answers. Verifiable sources. Zero guesswork.
        </p>
      </div>

      <GlassCards label="What Atlas reads" features={FEATURES} />

      <p className="mt-8 text-center text-sm text-muted">
        Atlas answers from what you add here and shows the exact lines it used. Or go straight
        to the{" "}
        <Link href="/chat" className="text-cyan underline decoration-cyan/40 underline-offset-4">
          assistant
        </Link>
        ; allow the web, and it reaches further, saying where each answer came from.
      </p>
      <IngestForm />
    </main>
  );
}
