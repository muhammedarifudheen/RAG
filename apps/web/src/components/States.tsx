"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

/** Shown when a request runs long: a free server sleeps when idle. */
export const WAKING_HINT =
  "Still working. If nobody has used Atlas for a while, its server takes about a minute to wake up.";

/** True once `active` has lasted `afterMs`; false again when it ends. */
export function useTakingLong(active: boolean, afterMs = 12_000): boolean {
  const [long, setLong] = useState(false);
  useEffect(() => {
    setLong(false);
    if (!active) return;
    const timer = setTimeout(() => setLong(true), afterMs);
    return () => clearTimeout(timer);
  }, [active, afterMs]);
  return long;
}

export function Loading({ label }: { label: string }) {
  const long = useTakingLong(true);
  return (
    <div role="status" className="p-6 text-sm text-slate-500">
      <p>{label}</p>
      {long && <p className="mt-2">{WAKING_HINT}</p>}
    </div>
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
