import type { Config } from "tailwindcss";

// "Liquid light": an airy off-white page with slow pastel waves behind it, white glass
// panels floating on soft shadows, one violet accent and a mint highlight. The token
// names are kept from the first design (ink is the page, paper the text). The colours
// are also in globals.css.
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#f6f6fb", // page
        panel: "#ffffff", // cards, bars
        raised: "#f0f1f8", // hover, inputs
        line: "#e3e4ee",
        "line-strong": "#c9cbdb",
        paper: "#161827", // text
        soft: "#3d4057",
        muted: "#6b6f86",
        faint: "#9a9db2",
        signal: { DEFAULT: "#6b5cff", hover: "#5a4bf0" },
        acid: "#0fa985",
        cyan: "#0a7fb8",
        danger: "#d93d42",
        warn: "#b87400",
        ok: "#0f9d58",
      },
      fontFamily: {
        sans: ["var(--font-body)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-body)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        block: "0 18px 40px -18px rgba(76, 64, 190, 0.35), 0 2px 6px -2px rgba(22, 24, 39, 0.08)",
        "block-acid": "0 14px 32px -16px rgba(15, 169, 133, 0.45)",
        float: "0 30px 70px -30px rgba(76, 64, 190, 0.35), 0 8px 20px -12px rgba(22, 24, 39, 0.12)",
      },
      borderRadius: {
        glass: "22px",
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
