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
  used, as `[path:start-end]`, each checked against what the model was shown.
- **Then the web and general knowledge.** When your sources do not cover a question,
  it says so and answers anyway; for recent events it searches the web (Gemini's
  Google search when the key has that quota, or Groq's compound models).
- **Several AI services.** Gemini, Groq, OpenRouter, Mistral and Claude: each is used
  once its key is set (`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`,
  `MISTRAL_API_KEY`, `ANTHROPIC_API_KEY`). The **Auto** mode routes each question by
  type (your sources, code, recent events, reasoning, small talk, general) to the
  services and models that suit it; **Best model** always starts with the strongest.
  Either way, a busy or failing service hands over to the next one.
- **A chatbot.** Answers stream as they are written, follow-ups remember the
  conversation, three follow-up questions are suggested, and past chats are kept in
  the browser's sidebar.
- **Files and images.** Attach PDFs, EPUBs, web pages, code, CSV or text (read by
  `POST /attachments`; nothing is stored) and images (sent to the models that can see
  them). Drop or paste them into the message box; follow-ups still see them.
- **Pictures.** "Draw a lighthouse at dusk", or the Draw switch: a fast model writes a
  detailed prompt and [Pollinations](https://pollinations.ai) draws it (free, no key;
  `IMAGE_URL_TEMPLATE` points elsewhere).
- **Your settings.** Answer length (concise, balanced, detailed), creativity
  (temperature) and custom instructions sent with every question; answers read aloud.
- **Everything around it.** Copy, regenerate, edit a question and resend, copy code
  blocks (highlighted), maths typeset with KaTeX, voice input, search, pin and rename
  chats, export a chat as Markdown or all chats as JSON (and import them), share a
  chat by link (`POST /shares`; on the free server the links last until it restarts),
  and keyboard shortcuts (Ctrl+/ lists them).

The API side is `apps/api/app/assistant` (router, providers, prompt). `/ask` uses it
for streaming requests (`Accept: text/event-stream`) and for any request with
`history`, `attachments`, `style`, `temperature`, `instructions` or `task`; a plain JSON
question still gets the sources-only answer. Each service tries its best-suited models
first; when all of those fail, the rest of every service's models are tried, since free
quotas are counted per model.

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

The free server sleeps after 15 idle minutes; the first visit afterwards waits
about a minute while it starts, and the site says so. It keeps no data across
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
