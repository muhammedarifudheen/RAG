import Link from "next/link";

export function Loading({ label }: { label: string }) {
  return (
    <p role="status" className="p-6 text-sm text-slate-500">
      {label}
    </p>
  );
}

export function ErrorMessage({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="m-6 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
    >
      {message}
    </p>
  );
}

export function NothingIngested() {
  return (
    <p className="p-6 text-sm text-slate-600">
      No repository has been ingested yet.{" "}
      <Link href="/" className="text-indigo-700 underline">
        Ingest one
      </Link>{" "}
      to see it here.
    </p>
  );
}
