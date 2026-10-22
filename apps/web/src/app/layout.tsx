import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Space_Grotesk, Unbounded } from "next/font/google";

import { Nav } from "@/components/Nav";

import "katex/dist/katex.min.css";
import "./globals.css";

// Unbounded for display type (wide, Y2K), Space Grotesk for text, JetBrains Mono for
// code and labels. next/font serves them from the site itself.
const display = Unbounded({ subsets: ["latin"], variable: "--font-display", display: "swap" });
const body = Space_Grotesk({ subsets: ["latin"], variable: "--font-body", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Atlas",
  description: "An AI assistant over your own sources: ask, attach, draw, search and inspect.",
};

export const viewport: Viewport = { themeColor: "#0a0a0b" };

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body className="flex min-h-screen flex-col bg-ink font-sans text-paper antialiased">
        <Nav />
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </body>
    </html>
  );
}
