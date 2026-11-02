"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { applyTheme, currentTheme, type Theme } from "@/lib/theme";

import { DragonMark } from "./Ornament";

const LINKS = [
  { href: "/", label: "Ingest" },
  { href: "/chat", label: "Chat" },
  { href: "/graph", label: "Graph" },
  { href: "/health", label: "Health" },
  { href: "/analyze", label: "Analyse" },
  { href: "/insights", label: "Insights" },
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
          {/* The mark: the glass dragon coiled round its pearl. */}
          <DragonMark className="h-8 w-8 drop-shadow-[0_0_10px_rgba(51,214,240,0.55)]" />
          <span className="chrome-text font-display text-[20px] font-semibold uppercase tracking-[0.22em]">
            Atlas
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
                      ? "bg-signal/90 text-on-signal shadow-glow"
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
