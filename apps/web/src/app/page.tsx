import Link from "next/link";

import { IngestForm } from "@/components/IngestForm";
import { MughalArch, StarRule } from "@/components/Ornament";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      {/* The heading stands in a cusped arch, like a portal's pishtaq. */}
      <div className="relative mx-auto max-w-2xl px-8 pb-10 pt-24 text-center sm:px-14 sm:pt-28">
        <MughalArch className="absolute inset-0 h-full w-full" />
        <p className="label relative flex items-center justify-center gap-3 text-muted">
          <span className="bg-signal px-1.5 py-0.5 text-on-signal">01</span>
          Sources
        </p>
        <h1 className="relative mt-5 font-display text-5xl font-semibold leading-[1.02] tracking-tight sm:text-6xl">
          Build a <span className="chrome-text italic">knowledge</span> base
        </h1>
        <StarRule className="relative mx-auto mt-6 max-w-xs" />
        <p className="label relative mt-5 text-signal">
          Grounded answers. Verifiable sources. Zero guesswork.
        </p>
      </div>
      <p className="mx-auto mt-8 max-w-2xl text-center text-soft">
        Add code repositories, web pages, Wikipedia articles and your own documents. Atlas reads
        them, then answers questions from what they say and shows you the exact lines it used.
        For code (Python, TypeScript and Go) it also maps functions, classes and the calls
        between them.
      </p>
      <p className="mt-4 text-center text-sm text-muted">
        Or go straight to the{" "}
        <Link href="/chat" className="text-cyan underline decoration-cyan/40 underline-offset-4">
          assistant
        </Link>
        : it answers from these sources and cites the lines it used. Allow the web, and it
        reaches further, saying where each answer came from.
      </p>
      <IngestForm />
    </main>
  );
}
