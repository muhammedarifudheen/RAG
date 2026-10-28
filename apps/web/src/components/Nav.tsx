"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Ingest" },
  { href: "/chat", label: "Chat" },
  { href: "/graph", label: "Graph" },
  { href: "/health", label: "Health" },
  { href: "/analyze", label: "Analyse" },
];

/** A glass bar floating over the page. */
export function Nav() {
  const pathname = usePathname();

  return (
    <header className="relative z-20 px-3 pt-3">
      <nav
        aria-label="Main"
        className="glass mx-auto flex h-12 max-w-6xl items-center gap-1 rounded-full pl-2 pr-3 shadow-float"
      >
        <Link
          href="/chat"
          className="flex items-center gap-2 rounded-full py-1 pl-1 pr-3"
          aria-label="Atlas home"
        >
          {/* The mark: a soft orb of the accent colours. */}
          <span
            aria-hidden="true"
            className="h-7 w-7 rounded-full bg-[conic-gradient(from_200deg,#6b5cff,#3aa0ff,#12b88f,#ffb4c8,#6b5cff)] shadow-[0_0_18px_-2px_rgba(107,92,255,0.6)]"
          />
          <span className="chrome-text font-display text-[17px] font-semibold tracking-tight">
            atlas
          </span>
        </Link>

        <ul className="flex items-center gap-0.5 overflow-x-auto">
          {LINKS.map(({ href, label }) => {
            const active = pathname === href;
            return (
              <li key={href} className="flex">
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-full px-3 py-1.5 text-[13px] transition-colors ${
                    active
                      ? "bg-paper text-ink shadow-[0_6px_16px_-8px_rgba(22,24,39,0.5)]"
                      : "text-muted hover:bg-white/70 hover:text-paper"
                  }`}
                >
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>

        <p className="ml-auto hidden items-center gap-2 text-[12px] text-muted md:flex">
          <span aria-hidden="true" className="h-1.5 w-1.5 animate-pulse rounded-full bg-acid" />
          Multi-model AI
        </p>
      </nav>
    </header>
  );
}
