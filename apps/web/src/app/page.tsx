import Link from "next/link";

import { IngestForm } from "@/components/IngestForm";

const READS = ["Repositories", "Web & Wikipedia", "Documents", "Code files"];

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-12 sm:py-20">
      {/* Text on the left; the dragon is the page's backdrop, on the right. */}
      <div className="max-w-xl">
        <p className="label text-signal">01 — Sources</p>
        <h1 className="mt-6 font-display text-5xl font-semibold leading-[0.95] tracking-tight sm:text-7xl">
          Grounded answers.
          <br />
          <span className="text-signal">Zero guesswork.</span>
        </h1>
        <p className="mt-8 max-w-md text-[15px] leading-relaxed text-muted">
          Atlas answers from what you add here and shows the exact lines it used. Or go straight
          to the{" "}
          <Link href="/chat" className="text-paper underline decoration-signal underline-offset-4">
            assistant
          </Link>
          .
        </p>
        <ul aria-label="What Atlas reads" className="label mt-8 flex flex-wrap gap-x-5 gap-y-2 text-faint">
          {READS.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <div className="mt-12">
          <IngestForm />
        </div>
      </div>
    </main>
  );
}
