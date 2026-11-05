"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { applyTheme, currentTheme, type Theme } from "@/lib/theme";

import { DragonMark } from "./DragonImage";

const LINKS = [
  { href: "/", label: "Ingest" },
  { href: "/chat", label: "Chat" },
  { href: "/graph", label: "Graph" },
  { href: "/health", label: "Health" },
  { href: "/analyze", label: "Analyse" },
  { href: "/insights", label: "Insights" },
];

/** A single hairline bar: the mark, the pages, the theme. */
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
    <header className="relative z-20 border-b border-line bg-ink/80 backdrop-blur-sm">
      <nav aria-label="Main" className="mx-auto flex h-12 max-w-6xl items-center gap-6 px-4">
        <Link href="/chat" className="flex items-center gap-3" aria-label="Atlas home">
          <DragonMark />
          <span className="font-display text-[15px] font-semibold uppercase tracking-[0.34em]">
            Atlas
          </span>
        </Link>

        <ul className="flex h-full items-stretch overflow-x-auto">
          {LINKS.map(({ href, label }) => {
            const active = pathname === href;
            return (
              <li key={href} className="flex">
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`label flex items-center border-b px-3 transition-colors duration-300 ${
                    active
                      ? "border-signal text-paper"
                      : "border-transparent text-muted hover:text-paper"
                  }`}
                >
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>

        <button
          type="button"
          onClick={() => applyTheme(theme === "dark" ? "light" : "dark")}
          aria-label={theme === "dark" ? "Switch to the light theme" : "Switch to the dark theme"}
          title={theme === "dark" ? "Light theme" : "Dark theme"}
          className="ml-auto flex h-8 w-8 items-center justify-center text-muted transition-colors duration-300 hover:text-signal"
        >
          <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
        </button>
      </nav>
    </header>
  );
}
