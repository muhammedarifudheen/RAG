"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { checkAdmin, setAdminToken } from "@/lib/api";

/** Shown to visitors of a public deployment, where managing sources needs a password. */
export function AdminUnlock({ onUnlock }: { onUnlock: () => void }) {
  const [password, setPassword] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setChecking(true);
    setError(null);
    try {
      if (await checkAdmin(password)) {
        setAdminToken(password);
        onUnlock();
      } else {
        setError("That is not the admin password.");
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not check the password.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <section aria-labelledby="public-heading" className="mt-8 rounded-lg border border-slate-200 bg-white p-4">
      <h2 id="public-heading" className="text-sm font-semibold text-slate-900">
        This is a public Atlas
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        Anyone can{" "}
        <Link href="/chat" className="text-indigo-700 underline">
          ask questions
        </Link>{" "}
        about the sources below, and browse the graph and health pages. Adding or removing
        sources is limited to the site&apos;s admin.
      </p>
      <form onSubmit={onSubmit} className="mt-3 flex flex-col gap-2 sm:flex-row">
        <label htmlFor="admin-password" className="sr-only">
          Admin password
        </label>
        <input
          id="admin-password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Admin password"
          autoComplete="current-password"
          className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200"
        />
        <button
          type="submit"
          disabled={checking || password === ""}
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
        >
          {checking ? "Checking…" : "Unlock"}
        </button>
      </form>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      )}
    </section>
  );
}
