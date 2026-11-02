import Link from "next/link";

import { IngestForm } from "@/components/IngestForm";
import { Charbagh, Pishtaq, StarRule, type Quadrant } from "@/components/Ornament";

// What Atlas reads, laid out as a charbagh: four quadrants, each its own stone.
const QUADRANTS: Quadrant[] = [
  {
    title: "Repositories",
    text: "GitHub code, mapped to its functions, classes and the calls between them.",
    stone: "lapis",
  },
  {
    title: "Web & Wikipedia",
    text: "Pages, whole sites and articles, each credited with its licence.",
    stone: "turquoise",
  },
  {
    title: "Documents",
    text: "PDF, EPUB, Word, Markdown and text, split where their sections do.",
    stone: "carnelian",
  },
  {
    title: "Code files",
    text: "Python, TypeScript and Go, parsed like a repository of one.",
    stone: "jade",
  },
];

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      {/* The heading in a pishtaq: an inlaid frame around a pointed-arch recess. */}
      <Pishtaq className="mx-auto max-w-2xl">
        <div className="px-8 pb-12 pt-24 text-center sm:px-16 sm:pt-28">
          <p className="label flex items-center justify-center gap-3 text-muted">
            <span className="bg-signal px-1.5 py-0.5 text-on-signal">01</span>
            Sources
          </p>
          <h1 className="mt-5 font-display text-4xl font-semibold leading-[1.02] tracking-tight sm:text-6xl">
            Build a <span className="chrome-text italic">knowledge</span> base
          </h1>
          <StarRule className="mx-auto mt-6 max-w-xs" />
          <p className="label mt-5 text-signal">
            Grounded answers. Verifiable sources. Zero guesswork.
          </p>
        </div>
      </Pishtaq>

      <Charbagh label="What Atlas reads" quadrants={QUADRANTS} />

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
