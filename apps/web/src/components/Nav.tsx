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
    <header className="border-b border-slate-200 bg-white">
      <nav aria-label="Main" className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-4">
        <span className="text-base font-semibold tracking-tight">Atlas</span>
        <ul className="flex gap-1 text-sm">
          {LINKS.map(({ href, label }) => {
            const active = pathname === href;
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3 py-1.5 ${
                    active
                      ? "bg-indigo-50 font-medium text-indigo-700"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  }`}
                >
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}
