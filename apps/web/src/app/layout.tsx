import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";

import { DragonBackdrop } from "@/components/DragonImage";
import { Nav } from "@/components/Nav";
import { THEME_SCRIPT } from "@/lib/theme";

import "katex/dist/katex.min.css";
import "./globals.css";

// Space Grotesk for headings, Inter for text, JetBrains Mono for code, labels and citations.
// next/font serves them from the site.
const display = Space_Grotesk({
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

export const viewport: Viewport = { themeColor: "#000000" };

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
        <DragonBackdrop />
        <Nav />
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </body>
    </html>
  );
}
