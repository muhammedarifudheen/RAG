import { IngestForm } from "@/components/IngestForm";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-20">
      <h1 className="text-3xl font-semibold tracking-tight">Understand a codebase</h1>
      <p className="mt-3 text-slate-600">
        Atlas clones a repository, maps its functions, classes and the calls between them, and
        lets you search it, ask questions about it and inspect its structure. Python, TypeScript
        and Go are supported.
      </p>
      <IngestForm />
    </main>
  );
}
