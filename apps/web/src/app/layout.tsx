import type { Metadata, Viewport } from "next";
import { Cormorant_Garamond, Inter, JetBrains_Mono } from "next/font/google";

import { Nav } from "@/components/Nav";
import { THEME_SCRIPT } from "@/lib/theme";

import "katex/dist/katex.min.css";
import "./globals.css";

// Cormorant Garamond for headings (high-contrast couture serif), Inter for text,
// JetBrains Mono for code, labels and citations. next/font serves them from the site.
const display = Cormorant_Garamond({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
  display: "swap",
});
const body = Inter({ subsets: ["latin"], variable: "--font-body", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Atlas",
  description: "Grounded answers. Verifiable sources. Zero guesswork.",
};

export const viewport: Viewport = { themeColor: "#07080b" };

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <head>
        {/* The theme and contrast before the first paint, so the page never flashes. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="flex min-h-screen flex-col font-sans text-paper antialiased">
        {/* A frieze of pietra dura along the top, as on a Mughal facade. */}
        <div aria-hidden="true" className="inlay-band h-3 shrink-0" />
        <Nav />
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </body>
    </html>
  );
}
