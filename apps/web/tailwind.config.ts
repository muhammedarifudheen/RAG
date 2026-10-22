import type { Config } from "tailwindcss";

// Dark only. Minimal surfaces, Constructivist signal red and heavy type, Y2K chrome,
// acid lime and monospace details. The colours are also in globals.css.
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0a0a0b", // page
        panel: "#111113", // cards, bars
        raised: "#1b1b1f", // hover, inputs
        line: "#2a2a30",
        "line-strong": "#3d3d46",
        paper: "#eee9df", // text
        soft: "#c3beb4",
        muted: "#8b8891",
        faint: "#5c5a62",
        signal: { DEFAULT: "#ff3d1f", hover: "#ff5d43" },
        acid: "#d7ff3b",
        cyan: "#79f2ff",
        danger: "#ff6b5b",
        warn: "#ffc247",
        ok: "#7dffaa",
      },
      fontFamily: {
        sans: ["var(--font-body)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-body)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        block: "4px 4px 0 0 #ff3d1f",
        "block-acid": "4px 4px 0 0 #d7ff3b",
      },
    },
  },
  plugins: [],
};

export default config;
