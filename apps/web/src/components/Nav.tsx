"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Ingest" },
  { href: "/chat", label: "Chat" },
  { href: "/graph", label: "Graph" },
  { href: "/health", label: "Health" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <header className="relative z-20 border-b border-line bg-ink/95 backdrop-blur">
      <nav aria-label="Main" className="flex h-14 items-stretch gap-2 pr-4">
        {/* The mark: a red slab cut on the diagonal, chrome lettering, an acid star. */}
        <Link
          href="/chat"
          className="relative flex items-center gap-2 pl-4 pr-8"
          aria-label="Atlas home"
        >
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-0 w-full bg-signal [clip-path:polygon(0_0,100%_0,calc(100%-18px)_100%,0_100%)]"
          />
          <span className="relative font-display text-[17px] font-extrabold tracking-[0.08em] text-ink">
            ATLAS
          </span>
          <span aria-hidden="true" className="relative text-sm text-ink">
            ✦
          </span>
        </Link>

        <ul className="flex items-stretch overflow-x-auto">
          {LINKS.map(({ href, label }, index) => {
            const active = pathname === href;
            return (
              <li key={href} className="flex">
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`group flex items-center gap-1.5 border-b-2 px-3 font-mono text-[11px] uppercase tracking-[0.16em] transition-colors ${
                    active
                      ? "border-signal text-paper"
                      : "border-transparent text-muted hover:border-line-strong hover:text-paper"
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className={active ? "text-signal" : "text-faint group-hover:text-muted"}
                  >
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>

        <p className="label ml-auto hidden items-center gap-2 text-muted md:flex">
          <span aria-hidden="true" className="h-1.5 w-1.5 animate-pulse rounded-full bg-acid" />
          Multi-model AI
        </p>
      </nav>
    </header>
  );
}
