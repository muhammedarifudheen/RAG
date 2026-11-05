import { fileURLToPath } from "node:url";

import type { Config } from "tailwindcss";

// "Black court": near-black, hairlines, one teal light (and a light theme): the colours are CSS variables, RGB triplets set
// in globals.css per theme, so every class follows the theme. The token names are kept
// from the first design (ink is the page, paper the text).
const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  // Absolute, so it holds whichever directory the build starts from.
  content: [fileURLToPath(new URL("./src/**/*.{ts,tsx}", import.meta.url))],
  theme: {
    extend: {
      colors: {
        ink: v("ink"), // page
        panel: v("panel"), // cards, bars
        raised: v("raised"), // hover, inputs
        line: v("line"),
        "line-strong": v("line-strong"),
        paper: v("paper"), // text
        soft: v("soft"),
        muted: v("muted"),
        faint: v("faint"),
        signal: { DEFAULT: v("signal"), hover: v("signal-hover") },
        "on-signal": v("on-signal"), // text on the accent
        acid: v("acid"),
        cyan: v("cyan"),
        danger: v("danger"),
        warn: v("warn"),
        ok: v("ok"),
      },
      fontFamily: {
        sans: ["var(--font-body)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-body)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        block: "0 0 0 1px rgb(var(--line-strong))",
        "block-acid": "0 14px 32px -16px rgb(var(--acid) / 0.5)",
        float: "var(--shadow)",
        glow: "var(--glow)",
      },
      // Sharp: everything is a hairline box, pills and dots included.
      borderRadius: {
        none: "0",
        sm: "1px",
        DEFAULT: "2px",
        md: "2px",
        lg: "2px",
        xl: "2px",
        "2xl": "2px",
        "3xl": "2px",
        glass: "2px",
        full: "2px",
      },
      keyframes: {
        drift: {
          "0%, 100%": { transform: "translate3d(0, 0, 0) scale(1)" },
          "33%": { transform: "translate3d(4%, -3%, 0) scale(1.06)" },
          "66%": { transform: "translate3d(-3%, 4%, 0) scale(0.97)" },
        },
        rise: {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        drift: "drift 26s ease-in-out infinite",
        "drift-slow": "drift 38s ease-in-out infinite reverse",
        rise: "rise 0.45s cubic-bezier(0.2, 0.7, 0.2, 1) both",
      },
    },
  },
  plugins: [],
};

export default config;
