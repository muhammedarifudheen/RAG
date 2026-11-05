import { fileURLToPath } from "node:url";

// Tailwind finds its config in the working directory by default; point it at this folder's
// own, so a build started from the repository root (or an editor) still scans src/.
const tailwindConfig = fileURLToPath(new URL("./tailwind.config.ts", import.meta.url));

/** @type {import('postcss-load-config').Config} */
const config = {
  plugins: {
    tailwindcss: { config: tailwindConfig },
    autoprefixer: {},
  },
};

export default config;
