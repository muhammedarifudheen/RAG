# atlas

Builds a knowledge base from GitHub repositories, web pages, Wikipedia articles
and your own documents (PDF, EPUB, text, Markdown), and answers questions from
it with citations down to the line. For code it also builds a graph of
functions, classes and calls, with code-health queries over it.

Sources accumulate: adding one leaves the others in place, and each can be
removed on its own.

| Path               | What it is                                    |
| ------------------ | --------------------------------------------- |
| `apps/web`         | Next.js UI: ingest, chat, dependency graph, health dashboard |
| `apps/api`         | FastAPI service: `/ingest`, `/search`, `/ask`, `/graph`, `/health` |
| `apps/worker`      | Ingestion pipeline: clone, parse, embed, store |
| `packages/shared`  | The API's types for TypeScript, used by the web app |
| `docker-compose.yml` | Postgres 16 with pgvector                   |

JavaScript is managed with pnpm workspaces (`apps/web`, `packages/*`).
Each Python app has its own virtualenv at `apps/<app>/.venv`.

## Prerequisites

- Node.js 18.17+ and pnpm 9+
- Python 3.11+
- Docker with Compose v2

## Quick start: everything in Docker

Needs only Docker.

```sh
cp .env.example .env        # set ANTHROPIC_API_KEY here to use the chat page
docker compose up --build
```

Then open http://localhost:3000 and paste a GitHub repository URL. The API is
on http://localhost:8000 (docs at `/docs`). The first build downloads PyTorch
and the embedding model and takes several minutes; later starts are quick.

This starts Postgres, applies the migrations, then starts the API and the web
app. `docker compose down` stops it; add `-v` to delete the database as well.

Use the steps below instead when you want to edit code and see changes without
rebuilding images.

### No Docker on your machine?

`scripts/run-in-cloud-shell.ps1` runs the same compose stack on Google Cloud
Shell (a free Linux VM that comes with a Google account; no project or billing)
and forwards it to http://127.0.0.1:3000 on your machine. It needs the `gcloud`
CLI, signed in:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-in-cloud-shell.ps1
```

Leave the window open; it reconnects when the link drops. It is a stopgap:
Google recycles the VM when idle, which loses the ingested data, and the script
then rebuilds the stack. Details are in the comment at the top of the script.

## Getting started: running the apps on your machine

### 1. Database

```sh
cp .env.example .env        # optional, defaults work
docker compose up -d postgres
```

Postgres listens on `localhost:5432` (user, password and database are all
`atlas`). The `vector` extension is created the first time the data volume is
initialised, by `docker/postgres/init/01-extensions.sql`. The same step creates
an `atlas_test` database for the API test suite. To re-run the init scripts,
drop the volume with `docker compose down -v`.

### 2. API

Create the venv, install and migrate as described in
[apps/api/README.md](apps/api/README.md), then:

```sh
uvicorn app.main:app --reload          # apps/api, http://localhost:8000
```

Set `ANTHROPIC_API_KEY` in `apps/api/.env` to use the chat page.

### 3. Web

```sh
pnpm install
pnpm dev                    # http://localhost:3000
```

Open http://localhost:3000 and paste a GitHub repository URL. The web app
proxies `/api/*` to the API, which runs the ingestion itself.

### Worker CLI

`apps/worker` has its own venv and a CLI for ingesting without the UI; see
[apps/worker/README.md](apps/worker/README.md).

## The chat assistant

The chat page answers any question, not only questions about your sources:

- **Sources first.** It searches your knowledge base and cites the exact lines it
  used, as `[path:start-end]`, each checked against what the model was shown. A query
  planner (a fast model, about a second) first turns the question into several searches:
  the question cleaned up, its keywords, a hypothetical answer sentence (HyDE) and a broader
  or narrower variant. Their results are fused by reciprocal rank, so excerpts several
  searches agree on come first; the answer lists the searches (Settings → Retrieval turns
  planning off; `plan_queries: false` on `/ask`).
- **Today's facts, every time.** Before answering (anything but small talk) it searches
  the web and gives every agent the results, so versions, news, prices, scores and
  who-holds-what come from today, with dates and links: Google News and Wikipedia (no
  key needed), plus Tavily or Brave Search when `TAVILY_API_KEY` or `BRAVE_API_KEY` is
  set. Gemini also searches Google itself when its key has that quota. You see the
  results it found while the council works, and the answer links them.
- **A council of AI agents.** Up to 12 agents on different services answer each
  question in parallel; one model (the strongest that just answered) then merges their
  best points into the answer you see, settling disagreements and dropping mistakes
  (the quickest service that answered merges, so the answer starts within seconds).
  You watch the council work: each agent shows as thinking, answered, failed or too
  slow. An agent that fails (out of quota, overloaded) is replaced by the next model in
  line, and slow agents are not waited for: four seconds after two have answered, the
  merge starts.
- **Every free AI service.** Gemini, OpenRouter (every free model in its catalogue),
  GitHub Models, Mistral, Cerebras, Groq, DeepSeek, SambaNova, NVIDIA, Cohere, Hugging Face,
  Cloudflare Workers AI, Together and Claude join the council once their key is set
  (see `.env.example`); Pollinations and AI Horde need no key and are always there. The
  **Auto** mode orders agents by question type (your sources, code, recent events,
  reasoning, small talk, general); **Best model** puts the strongest first.
- **A chatbot.** Answers stream as they are written, follow-ups remember the
  conversation, three follow-up questions are suggested, and past chats are kept in
  the browser's sidebar.
- **Files and images.** Attach PDFs, EPUBs, web pages, code, CSV or text (read by
  `POST /attachments`; nothing is stored) and images (sent to the models that can see
  them). Drop or paste them into the message box; follow-ups still see them.
- **Pictures.** "Draw a lighthouse at dusk", or the Draw switch: a fast model writes a
  detailed prompt (subject, medium, lighting, composition) and up to eight picture agents
  draw it at once, shown as a gallery as each picture arrives:
  [Pollinations](https://pollinations.ai) FLUX and one [AI Horde](https://aihorde.net)
  agent per model (AlbedoBase XL, Juggernaut XL, Deliberate; free, no key, with a
  negative prompt against blur and artefacts), plus FLUX on Cloudflare, Hugging Face and
  Together when their keys are set, and Gemini's image model with `GEMINI_IMAGES=true`
  (it needs billing). A free `HORDE_API_KEY` moves the Horde agents up the queue.
- **A code analyser.** Ask to review or audit code (pasted, attached, a link to a file
  on GitHub, or a whole public repository) and real checks run first: Ruff's bug and
  security rules (Bandit's) on Python, a scan for leaked keys, risky patterns in
  JavaScript, TypeScript and Go (eval, HTML injection, SQL built from strings, TLS checks
  turned off), each function's cyclomatic complexity and nesting from its syntax tree,
  and for a repository its import cycles, most depended-on and riskiest files. The
  council then reviews the findings as principal engineers would: confirmed issues with
  `path:line` and a fix, false positives dismissed, logic and design problems the
  checkers cannot see. The **Analyse** page does this for a repository and shows the
  report: a score and grade, the riskiest files, cycles, complex functions and every
  finding by severity. Nothing is stored; the clone is deleted.
- **Every control, in Settings.** *Answers*: length (concise, balanced, detailed),
  creativity (temperature), a persona (senior engineer, teacher, researcher, analyst,
  writer), the output format (Markdown, plain text or JSON), the maximum length in tokens,
  custom instructions and reading answers aloud. *Models*: which AI services may answer,
  how many agents sit on the council (1 is a single, fastest model) and which service
  merges. *Retrieval*: search your sources or not, how many excerpts (top-k), the
  relevance threshold, web search on or off, and **Strict sources only** (also a switch
  by the message box): your own retrieval-grounded rules, so every claim is cited from the
  knowledge base or attached files, or Atlas says "I don't have that in the knowledge
  base." (no model is asked when nothing was retrieved). *Transparency*: each agent's own draft
  and time under the merged answer. Only changed settings are sent (`services`,
  `council_size`, `merger`, `use_sources`, `top_k`, `min_score`, `web_search`,
  `max_tokens`, `format`, `include_drafts`, `strict` on `/ask`).
- **Liquid light.** A calm, airy design: pastel waves drift behind floating glass panels.
- **Everything around it.** Copy, regenerate, edit a question and resend, copy code
  blocks (highlighted), maths typeset with KaTeX, voice input, search, pin and rename
  chats, export a chat as Markdown or all chats as JSON (and import them), share a
  chat by link (`POST /shares`; on the free server the links last until it restarts),
  and keyboard shortcuts (Ctrl+/ lists them).

The API side is `apps/api/app/assistant` (router, providers, prompt). `/ask` uses it
for streaming requests (`Accept: text/event-stream`) and for any request with
`history`, `attachments`, `style`, `temperature`, `instructions` or `task`; a plain JSON
question still gets the sources-only answer. `ASSISTANT_COUNCIL_SIZE=1` turns the
council off: then one model answers, and when it fails the next takes over (each
service's best-suited models first, then the rest, since free quotas are per model).

## Deployment and CI

Staging runs on Google Cloud (Cloud Run and Cloud SQL), deployed by GitHub
Actions on every merge to `main`; pull requests run all three test suites. See
[infra/README.md](infra/README.md).

### Public website (free): GitHub Pages + Render

Anyone can search and ask questions; only you can add or remove sources, with
an admin password. The site is static files on GitHub Pages. The server, from
[deploy/server/Dockerfile](deploy/server/Dockerfile), runs on Render's free plan:
Postgres, the API and the embedding model in one container that fits in 512 MB.

1. Deploy the server. You need a Render account and an
   [API key](https://dashboard.render.com/u/settings#api-keys):

   ```powershell
   .\scripts\deploy-render.ps1 -ApiKey <render_api_key> -SiteOrigin https://<github-user>.github.io
   ```

   The script prints the admin password and the server's address. It reads
   the model key (`GEMINI_API_KEY` or `ANTHROPIC_API_KEY`) from `.env`.
   Alternatively, in Render's dashboard choose New → Blueprint and select this
   repository; [render.yaml](render.yaml) describes the same service.
2. In the GitHub repository's settings:
   - Under Pages, set the source to **GitHub Actions**.
   - Under Secrets and variables → Actions → Variables, add `PUBLIC_API_URL` =
     the server's address (`https://atlas-api-….onrender.com`).
3. Re-run the **Publish website** workflow. The site is published at
   `https://<github-user>.github.io/<repo>/`.
4. To redeploy the server on every push, add the repository secret
   `RENDER_API_KEY` and variable `RENDER_SERVICE_ID` (the service's `srv-…` id).
   The **Deploy server** workflow then runs the tests, deploys, and fails if
   Render's deploy does. (Render's own auto-deploy needs its GitHub app.)

To check the live site in a real browser (home, admin lock, chat with verified
citations, the assistant with follow-ups and saved chats, attachments, pictures,
sharing, graph, health), run `node live-check.mjs` in `apps/web`; set
`SITE_URL` for a site other than this repository's.

The free server sleeps after 15 idle minutes, and waking it takes about a minute.
The "Keep the server awake" workflow ([keep-awake.yml](.github/workflows/keep-awake.yml))
calls it every ten minutes so it rarely sleeps (GitHub may run it late), and the chat
page starts waking it as soon as it opens. It keeps no data across
restarts, so the starter sources in its `SEED_SOURCES` setting are built into
the server's image ([deploy/server/bake.sh](deploy/server/bake.sh)) and are there
as soon as it starts. Sources an admin adds later are lost at the next restart;
to keep one, add it to `SEED_SOURCES` (Render then rebuilds the image).

## Root scripts

| Command          | Does                                  |
| ---------------- | ------------------------------------- |
| `pnpm dev`       | Run the web app in dev mode           |
| `pnpm build`     | Build every JS workspace package      |
| `pnpm lint`      | Lint every JS workspace package       |
| `pnpm typecheck` | Type-check every JS workspace package |
| `pnpm db:up`     | Start Postgres                        |
| `pnpm db:down`   | Stop Postgres                         |
