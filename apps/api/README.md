# atlas-api

FastAPI service over the code graph that `apps/worker` ingests: semantic search,
question answering with cited code, call graphs and a code-health report.

Built on SQLAlchemy 2 and Alembic, talking to Postgres (with pgvector) through
psycopg 3.

## Setup

From `apps/api`, with Postgres running (`docker compose up -d postgres` at the
repo root):

```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ../../packages/shared -e ../worker -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
```

```sh
# macOS / Linux
python -m venv .venv
source .venv/bin/activate
pip install -e ../../packages/shared -e ../worker -e ".[dev]"
cp .env.example .env
alembic upgrade head
```

The worker package is required: `POST /ingest` runs its pipeline inside the API
process. The install is large, because both ingestion and query embedding use a
sentence-transformers model, which pulls in PyTorch.

`/ask` needs Anthropic credentials. Set `ANTHROPIC_API_KEY` in `.env` or in the
environment; without it `/ask` answers `503` and every other endpoint works.

The query endpoints return nothing useful until a repository has been ingested,
through `POST /ingest` or the worker's CLI.

## Endpoints

Interactive docs are at http://localhost:8000/docs (ReDoc at `/redoc`, schema at
`/openapi.json`).

| Endpoint        | Does |
| --------------- | ---- |
| `POST /ingest`  | Ingests a GitHub repository, replacing the current one; progress is streamed as Server-Sent Events |
| `GET /search`   | Embeds `q` and returns the `limit` (default 20, max 50) most similar symbols, each with file path, line range and a code snippet |
| `POST /ask`     | Runs the same search, sends the top results and the question to Claude, returns the answer with inline citations plus the code chunks |
| `GET /graph`    | Call graph around `file`, up to `hops` calls away (default 1, max 5) |
| `GET /graph/files` | Every file and the dependencies between files, with circular ones marked |
| `GET /file`     | One file's source text and the symbols defined in it |
| `GET /health`   | Code-health report: dead symbols, circular dependencies, long functions, high fan-out files |
| `GET /healthz`  | Liveness probe; touches nothing and is not rate limited |

```sh
curl "http://localhost:8000/search?q=how+are+names+formatted&limit=5"
curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" \
     -d '{"question": "How are user names formatted?", "top_k": 8}'
curl "http://localhost:8000/graph?file=pkg/service.py&hops=2&direction=callees"
curl "http://localhost:8000/health?max_function_loc=50&min_fan_out=10"
```

### `/ingest`

```sh
curl -N -X POST http://localhost:8000/ingest -H "Content-Type: application/json" \
     -d '{"repo_url": "https://github.com/pallets/itsdangerous"}'
```

```
event: progress
data: {"step": 1, "total": 5, "message": "Cloning https://github.com/pallets/itsdangerous"}

event: progress
data: {"step": null, "total": null, "message": "parsed 15/15 files"}

event: done
data: {"files": 15, "symbols": 159, "edges": 180}
```

A `progress` event with a `step` starts that step; one with `step: null` is
detail within the current step. The stream ends with exactly one `done` or
`error` event. A comment line (`: keep-alive`) is sent every 15 seconds of
silence.

The pipeline is the worker's, run in a background thread of the API process:

- **It replaces everything previously ingested**, in one transaction. If it
  fails, the old data stays.
- **One ingest at a time.** A second request while one is running gets `409`.
- **It keeps running if the client disconnects**, and it cannot be cancelled.
- **It is heavy.** While it runs, the API process also clones, parses and
  embeds, and it loads a second copy of the embedding model. Restarting the API
  aborts a running ingest.
- Only `https://github.com/owner/repo` URLs are accepted (`422` otherwise).
  Private repositories need `GITHUB_TOKEN` in the environment.

The stream is a `POST` response, so browsers must read it with `fetch`;
`EventSource` only issues `GET` requests.

### `/search`

Results are ordered by cosine similarity (`score`, higher is closer). A symbol
longer than `SNIPPET_MAX_LINES` has its snippet cut short: `truncated` is true
and `snippet_end_line` says where it stops. The first request after startup
takes several seconds while the embedding model loads.

### `/ask`

Claude is shown each search result with line numbers and told to answer only
from that code, citing as `[path:start-end]`, for example
`[pkg/models.py:20-21]`.

The response has three parts worth knowing:

- `answer`: the text, with citations inline.
- `chunks`: the code that was sent to the model, most similar first.
- `citations`: every citation found in the answer. `verified` is true only when
  the cited lines lie inside one of the chunks. A false value means the model
  cited something it was not shown, so treat that claim with suspicion.

`complete` is false if the answer hit the token limit. The model defaults to
`claude-opus-5-5`. If it declines a request on policy grounds, Anthropic retries
on its recommended fallback model within the same call; `model` in the response
names whichever one answered.

| Status | Meaning |
| ------ | ------- |
| 409    | Nothing has been ingested |
| 422    | Invalid request, or the model declined to answer |
| 502    | The Anthropic API failed or was unreachable |
| 503    | Anthropic credentials missing or rejected, or Anthropic's rate limit hit |

### `/graph`

Starts from every symbol in the file (`depth` 0) and follows `calls` edges
outward one hop at a time. `direction` is `both` (default), `callees` (what the
file calls) or `callers` (what calls into it). Import and inheritance edges are
not part of the call graph. The result stops growing at 500 nodes and sets
`truncated`.

### `/graph/files` and `/file`

`/graph/files` collapses the symbol graph to files: one node per file, and one
edge per ordered pair of files with the number of `imports`, `calls` and
`inherits` edges between their symbols. Edges within a file are left out. Files
that depend on each other in a loop, and the edges forming it, have `in_cycle`
set; `cycles` lists the groups.

`/file?path=...` returns a file's full source and its symbols in line order.
The module symbol is omitted, since it is the file itself.

### `/health`

| Measure | Definition | Parameter |
| ------- | ---------- | --------- |
| Dead symbols | Functions and methods that nothing calls or imports | |
| Circular dependencies | Groups of files that depend on each other, and groups of symbols that call each other, directly or through intermediaries | |
| Long functions | Functions and methods longer than N lines | `max_function_loc` (50) |
| High fan-out files | Files that depend on at least N other files, through any edge | `min_fan_out` (10) |

`summary` gives the totals; each list is capped by `limit` (default 100).

Read **dead symbols** as candidates, not verdicts. The worker only records calls
it can resolve from syntax, so a method reached only through a variable
(`user.save()`) or declared on an interface has no incoming edge and is listed.
Entry points are excluded by name: `main`, `init`, `constructor`, dunder
methods, and anything starting with `test`. Classes are never listed.

Cycles are reported as groups (strongly connected components), not as individual
paths: three files that all reach each other appear as one group of three.

## Rate limiting and logging

Every endpoint except `/healthz` is limited per client IP over a sliding
one-minute window. The read endpoints (`/search`, `/graph`, `/graph/files`,
`/file`, `/health`) share one budget (`RATE_LIMIT_PER_MINUTE`, default 60).
`/ask` has its own (`ASK_RATE_LIMIT_PER_MINUTE`, default 10) because each call
is billed, and so does `/ingest` (`INGEST_RATE_LIMIT_PER_MINUTE`, default 5). Over the
limit, the response is `429` with a `Retry-After` header. Set a limit to `0` to
disable it.

The counters live in process memory. With several uvicorn workers each enforces
the limit separately, so the effective limit is multiplied by the worker count;
move them to a shared store such as Redis before relying on exact numbers. The
client is identified by the socket address, so behind a reverse proxy run
uvicorn with `--proxy-headers`, or every request will appear to come from the
proxy.

Each request is logged once on the `atlas.api.request` logger:

```
GET /search -> 200 in 17.4ms client=127.0.0.1 request_id=60ae828d726748b1902af56c6ed3d85c
```

The query string and body are deliberately not logged, since they contain
users' questions. The request ID is returned in the `X-Request-ID` header; a
caller-supplied `X-Request-ID` is reused if it is at most 64 characters of
letters, digits, `.`, `_` and `-`.

## Commands

Run from `apps/api` with the venv active.

| Command                                        | Does                                |
| ---------------------------------------------- | ----------------------------------- |
| `uvicorn app.main:app --reload`                | Dev server on http://localhost:8000 |
| `pytest`                                       | Run tests                           |
| `ruff check .`                                 | Lint                                |
| `alembic revision --autogenerate -m "message"` | Create a migration                  |
| `alembic upgrade head`                         | Apply migrations                    |
| `alembic downgrade -1`                         | Roll back one migration             |

## Tests

Most tests run against a real Postgres with pgvector, because the search query
uses pgvector's distance operator. They apply the Alembic migrations to a
dedicated database, then load a small hand-built graph from `tests/seed.py`.
The embedding model and Claude are replaced by fakes, so the tests need neither
PyTorch inference nor an API key.

The database defaults to `atlas_test` on the docker-compose Postgres, which
`docker/postgres/init/02-test-database.sql` creates on a fresh volume. On a
volume created before that file existed, create it once:

```sh
docker compose exec postgres createdb -U atlas atlas_test
```

To use another database, set `TEST_DATABASE_URL`. **The tests truncate the
tables**, so the suite refuses any database whose name does not end in `_test`.
If the database cannot be reached, the tests that need it are skipped and the
rest still run.

## Layout

```
app/
  main.py          App factory: middleware, error handling, routers, OpenAPI metadata
  config.py        Settings, loaded from the environment and .env
  db.py            Engine, session factory, get_db dependency
  schemas.py       Request and response models
  embedding.py     Query embedder (sentence-transformers), loaded on first use
  llm.py           Prompt construction and the Claude call
  ratelimit.py     In-memory sliding-window limiter
  middleware.py    Request logging and X-Request-ID
  routers/         ingest.py, search.py (/search, /ask), graph.py,
                   files.py (/graph/files, /file), health.py (/health, /healthz)
  services/        search.py, graph.py, files.py, health.py: the queries behind the routes
  models/          SQLAlchemy models; Base lives in base.py
migrations/        Alembic environment and versions/
tests/
  seed.py          Fixture graph and the fake embedder
```

New model modules must be imported in `app/models/__init__.py`, otherwise
Alembic autogenerate won't see them.

## Schema

Defined in `app/models/code_graph.py`. Migration `0001` creates the tables and
enables the `vector` extension; `0002` adds `files.content`.

| Table     | Columns                                                                  |
| --------- | ------------------------------------------------------------------------ |
| `files`   | `id`, `path` (unique), `language`, `hash`, `loc`, `content`              |
| `symbols` | `id`, `file_id`, `name`, `kind`, `start_line`, `end_line`, `signature`, `embedding vector(384)` |
| `edges`   | `id`, `from_symbol_id`, `to_symbol_id`, `kind`; unique per (from, to, kind) |

`symbols.kind` is one of `module`, `function`, `class`, `method`; `edges.kind`
is one of `calls`, `imports`, `inherits`. Both are enforced by CHECK
constraints. `symbols.embedding` has an HNSW index for cosine distance.
`files.content` holds each file's full source, which is where snippets come
from.

`apps/worker` imports these models to write the tables, and this app imports
the worker to run ingests, so the two packages depend on each other and are
always installed together. A change to the models is a change to the worker's
storage code too. See
[apps/worker/README.md](../worker/README.md) for what the rows mean.

## Environment

| Variable                    | Default                                                 | Purpose |
| --------------------------- | ------------------------------------------------------- | ------- |
| `DATABASE_URL`              | `postgresql+psycopg://atlas:atlas@localhost:5432/atlas` |         |
| `CORS_ORIGINS`              | `["http://localhost:3000"]`                             | JSON list |
| `LOG_LEVEL`                 | `INFO`                                                  |         |
| `EMBEDDING_MODEL`           | `sentence-transformers/all-MiniLM-L6-v2`                | Must match the worker's |
| `SNIPPET_MAX_LINES`         | `80`                                                    | Longest snippet returned or sent to Claude |
| `ANTHROPIC_API_KEY`         | unset                                                   | Required for `/ask` |
| `ANTHROPIC_MODEL`           | `claude-opus-5-5`                                       |         |
| `ANTHROPIC_EFFORT`          | `medium`                                                | `low` to `max`; higher is slower and costs more |
| `ANTHROPIC_MAX_TOKENS`      | `16000`                                                 | Cap on the answer, including the model's reasoning |
| `RATE_LIMIT_PER_MINUTE`     | `60`                                                    | `0` disables |
| `ASK_RATE_LIMIT_PER_MINUTE` | `10`                                                    | `0` disables |
| `INGEST_RATE_LIMIT_PER_MINUTE` | `5`                                                  | `0` disables |
| `GITHUB_TOKEN`              | unset                                                   | Read by the ingest pipeline; only needed for private repositories |
| `TEST_DATABASE_URL`         | `postgresql+psycopg://atlas:atlas@localhost:5432/atlas_test` | Tests only |
