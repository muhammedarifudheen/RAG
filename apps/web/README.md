# @atlas/web

The Atlas UI: Next.js 14 (App Router), TypeScript and Tailwind CSS 3.

| Page      | Does |
| --------- | ---- |
| `/`       | Paste a GitHub repo URL; ingestion progress streams in step by step |
| `/chat`   | Ask questions; answers render as Markdown, and each citation opens the cited code in a side panel |
| `/graph`  | Files as nodes, dependencies as edges, cycles in red; click a file to list its symbols |
| `/health` | Dead code, circular dependencies, and charts of function length and file fan-out |

## Setup

Install from the repo root so the workspace link to `@atlas/shared` resolves:

```sh
pnpm install
cp apps/web/.env.example apps/web/.env.local
```

The UI needs the API running (see [apps/api/README.md](../api/README.md)):

```sh
pnpm dev          # http://localhost:3000
```

## How it talks to the API

The browser only ever requests `/api/*` on the web app's own origin. A rewrite
in `next.config.mjs` proxies those to the FastAPI service at `API_URL`, so
`POST /api/ingest` in the browser becomes `POST /ingest` on the API. There is no
cross-origin request and the API's address never reaches client code.

`API_URL` is read when the app is **built** (`next build`) or when `next dev`
starts. Changing it for a production deployment means rebuilding.

The proxy's timeout is raised to ten minutes in `next.config.mjs`
(`experimental.proxyTimeout`). Its default of 30 seconds is shorter than many
chat answers take, and the browser would get a bare 500.

Every request and response type comes from `@atlas/shared`; the app defines no
API shapes of its own. `any` is rejected by ESLint
(`@typescript-eslint/no-explicit-any`).

## Commands

Run from the repo root with `pnpm --filter @atlas/web <script>`, or from this
directory with `pnpm <script>`.

| Script      | Does                                   |
| ----------- | -------------------------------------- |
| `dev`       | Dev server on http://localhost:3000    |
| `build`     | Production build                       |
| `start`     | Serve the production build             |
| `lint`      | ESLint (`next/core-web-vitals`, no `any`) |
| `typecheck` | `tsc --noEmit`                         |
| `test:e2e`  | Playwright tests                       |

## Tests

```sh
pnpm exec playwright install chromium     # once
pnpm test:e2e
```

The tests build the app for production, serve it on port 3100 and drive it in
Chromium. Every `/api/*` request is answered by the test itself, so they need no
API, database or Anthropic key. They cover the four main flows: streaming an
ingest, asking a question and opening a citation, exploring the graph, and
reading the health dashboard, plus the error and empty states of each.

Because the API is faked, these tests do not prove the two services agree. The
fixtures in `e2e/fixtures.ts` are typed with `@atlas/shared`, so a change to the
shared types breaks them at compile time, but a change to the API that is not
mirrored in the shared types will go unnoticed.

## Things worth knowing

- **Ingest progress** arrives as Server-Sent Events on a `POST` response.
  `EventSource` only supports `GET`, so `src/lib/sse.ts` reads the stream from
  `fetch` instead.
- **Chat is one question at a time.** The API's `/ask` takes no history, so
  earlier messages are shown but not sent along.
- **Citations** written as `[path:start-end]` become buttons. One the API could
  not verify (the model cited lines it was not shown) is amber and labelled
  "unverified". Citations inside code spans are left as text.
- **The code panel is loaded on demand**, in the browser only. Next.js refuses to
  bundle Shiki for the server, and importing it statically from a page breaks
  server rendering of that page; `next/dynamic` with `ssr: false` in
  `Chat.tsx` avoids that. Keep it that way if you move the panel.
- **Shiki** loads only the Python, TypeScript, TSX and Go grammars, matching
  what the worker parses, and uses its JavaScript regex engine (no WASM).
- **Graph layout** is computed once with d3-force when the data loads; React
  Flow draws it. Nodes can be dragged afterwards. Solid edges mean one file
  calls into the other, dashed ones that it only imports it.
- **"Complexity"** on the health page means function length and file fan-out.
  The API does not compute cyclomatic complexity.
- **The health page makes two requests**: one with the API's default thresholds
  for the summary and tables, and one with thresholds of 1 to get the top of
  each ranking for the charts.

## Layout

```
src/app/            Routes: page.tsx, chat/, graph/, health/; root layout and CSS
src/components/     IngestForm, Chat, Answer, CodePanel, FileGraphView, HealthDashboard, Nav
src/lib/
  api.ts            Typed calls to /api/*
  sse.ts            Server-Sent Events reader for fetch responses
  citations.ts      Finds citations in an answer and turns them into links
  highlight.ts      Shiki setup
  layout.ts         Force-directed layout
  useApi.ts         Loading/error/ready state for a request
e2e/                Playwright tests and their fixtures
```

`@/*` is aliased to `src/*`.

## Environment

| Variable  | Default                 | Purpose |
| --------- | ----------------------- | ------- |
| `API_URL` | `http://localhost:8000` | Where `/api/*` is proxied; read at build time and by `next dev` |
