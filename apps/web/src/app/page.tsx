import Link from "next/link";

import { IngestForm } from "@/components/IngestForm";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-14">
      <p className="label flex items-center gap-3 text-muted">
        <span className="bg-signal px-1.5 py-0.5 text-ink">01</span>
        Sources
        <span aria-hidden="true" className="h-px flex-1 bg-line" />
      </p>
      <h1 className="mt-6 font-display text-4xl font-extrabold uppercase leading-[1.05] tracking-tight sm:text-5xl">
        Build a <span className="chrome-text">knowledge</span>{" "}
        <span className="relative inline-block">
          base
          <span
            aria-hidden="true"
            className="absolute -bottom-1 left-0 h-2 w-full -skew-x-12 bg-signal"
          />
        </span>
      </h1>
      <p className="mt-6 max-w-2xl text-soft">
        Add code repositories, web pages, Wikipedia articles and your own documents. Atlas reads
        them, then answers questions from what they say and shows you the exact lines it used.
        For code (Python, TypeScript and Go) it also maps functions, classes and the calls
        between them.
      </p>
      <p className="mt-4 text-sm text-muted">
        Or go straight to the{" "}
        <Link href="/chat" className="text-cyan underline decoration-cyan/40 underline-offset-4">
          assistant
        </Link>
        : it answers anything, reads files you attach and draws pictures.
      </p>
      <IngestForm />
    </main>
  );
}
