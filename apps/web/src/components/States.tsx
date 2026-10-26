"use client";

import Link from "next/link";
export function Loading({ label }: { label: string }) {
  return (
    <div role="status" className="p-6 text-sm text-muted">
      <p>{label}</p>
    </div>
  );
}

export function ErrorMessage({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="m-6 border border-danger/40 bg-danger/10 p-4 text-sm text-danger"
    >
      {message}
    </p>
  );
}

export function NothingIngested() {
  return (
    <p className="p-6 text-sm text-soft">
      No repository has been ingested yet.{" "}
      <Link href="/" className="text-cyan underline">
        Ingest one
      </Link>{" "}
      to see it here.
    </p>
  );
}
