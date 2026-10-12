import { IngestForm } from "@/components/IngestForm";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">Build a knowledge base</h1>
      <p className="mt-3 text-slate-600">
        Add code repositories, web pages, Wikipedia articles and your own documents. Atlas reads
        them, then answers questions from what they say and shows you the exact lines it used.
        For code (Python, TypeScript and Go) it also maps functions, classes and the calls
        between them.
      </p>
      <IngestForm />
    </main>
  );
}
