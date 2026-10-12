# atlas

Ingests a GitHub repository into a code graph with embeddings, and serves
search, question answering and code-health queries over it.

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

## Deployment and CI

Staging runs on Google Cloud (Cloud Run and Cloud SQL), deployed by GitHub
Actions on every merge to `main`; pull requests run all three test suites. See
[infra/README.md](infra/README.md).

## Root scripts

| Command          | Does                                  |
| ---------------- | ------------------------------------- |
| `pnpm dev`       | Run the web app in dev mode           |
| `pnpm build`     | Build every JS workspace package      |
| `pnpm lint`      | Lint every JS workspace package       |
| `pnpm typecheck` | Type-check every JS workspace package |
| `pnpm db:up`     | Start Postgres                        |
| `pnpm db:down`   | Stop Postgres                         |
