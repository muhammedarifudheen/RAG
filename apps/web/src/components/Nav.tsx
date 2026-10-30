"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { applyTheme, currentTheme, type Theme } from "@/lib/theme";

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
  const [theme, setTheme] = useState<Theme>("dark");
  // The head script set the theme already; read it once mounted, and follow Settings.
  useEffect(() => {
    const follow = () => setTheme(currentTheme());
    follow();
    window.addEventListener("atlas-theme", follow);
    return () => window.removeEventListener("atlas-theme", follow);
  }, []);

  return (
    <header className="relative z-20 px-3 pt-3">
      <nav
        aria-label="Main"
        className="glass mx-auto flex h-12 max-w-6xl items-center gap-1 rounded-full pl-2 pr-2 shadow-float"
      >
        <Link
          href="/chat"
          className="flex items-center gap-2 rounded-full py-1 pl-1 pr-3"
          aria-label="Atlas home"
        >
          {/* The mark: a soft orb of the accent colours. */}
          <span
            aria-hidden="true"
            className="h-7 w-7 rounded-full bg-[conic-gradient(from_200deg,#8b7cff,#38bdf8,#34d399,#f0abfc,#8b7cff)] shadow-[0_0_22px_-2px_rgba(139,124,255,0.75)]"
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
                      ? "bg-signal/90 text-white shadow-glow"
                      : "text-muted hover:bg-raised/70 hover:text-paper"
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
        <button
          type="button"
          onClick={() => applyTheme(theme === "dark" ? "light" : "dark")}
          aria-label={theme === "dark" ? "Switch to the light theme" : "Switch to the dark theme"}
          title={theme === "dark" ? "Light theme" : "Dark theme"}
          className="ml-2 flex h-8 w-8 items-center justify-center rounded-full text-muted transition-colors hover:bg-raised hover:text-paper md:ml-3"
        >
          <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
        </button>
      </nav>
    </header>
  );
}
