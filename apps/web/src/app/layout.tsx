import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono, Sora } from "next/font/google";

import { Nav } from "@/components/Nav";

import "katex/dist/katex.min.css";
import "./globals.css";

// Sora for headings (geometric, a little futuristic), Inter for text, JetBrains Mono for
// code and labels. next/font serves them from the site itself.
const display = Sora({ subsets: ["latin"], variable: "--font-display", display: "swap" });
const body = Inter({ subsets: ["latin"], variable: "--font-body", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Atlas",
  description: "An AI assistant over your own sources: ask, attach, draw, search and inspect.",
};

export const viewport: Viewport = { themeColor: "#f6f6fb" };

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body className="flex min-h-screen flex-col font-sans text-paper antialiased">
        <Nav />
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </body>
    </html>
  );
}
