"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { checkAdmin, setAdminToken } from "@/lib/api";

/** Shown to visitors of a public deployment, where managing sources needs a password. */
export function AdminUnlock({ onUnlock, mfa = false }: { onUnlock: () => void; mfa?: boolean }) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setChecking(true);
    setError(null);
    try {
      if (await checkAdmin(password, mfa ? code : undefined)) {
        setAdminToken(password);
        onUnlock();
      } else {
        setError(
          mfa
            ? "That password or authenticator code is not right."
            : "That is not the admin password.",
        );
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not check the password.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <section aria-labelledby="public-heading" className="mt-8 border border-line bg-panel p-4">
      <h2 id="public-heading" className="text-sm font-semibold text-paper">
        This is a public Atlas
      </h2>
      <p className="mt-1 text-sm text-soft">
        Anyone can{" "}
        <Link href="/chat" className="text-cyan underline">
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
          className="min-w-0 flex-1 border border-line-strong bg-ink px-3 py-1.5 text-sm outline-none focus:border-signal focus:ring-2 focus:ring-signal/30"
        />
        {mfa && (
          <>
            <label htmlFor="admin-code" className="sr-only">
              Authenticator code
            </label>
            <input
              id="admin-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
              placeholder="6-digit code"
              className="w-32 border border-line-strong bg-ink px-3 py-1.5 font-mono text-sm outline-none focus:border-signal focus:ring-2 focus:ring-signal/30"
            />
          </>
        )}
        <button
          type="submit"
          disabled={checking || password === "" || (mfa && code.length !== 6)}
          className="border border-line-strong bg-panel px-3 py-1.5 text-sm hover:bg-raised disabled:cursor-not-allowed disabled:text-faint"
        >
          {checking ? "Checking…" : "Unlock"}
        </button>
      </form>
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
    </section>
  );
}
