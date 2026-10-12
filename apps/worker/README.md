# atlas-worker

Python ingestion worker. Clones a GitHub repository, extracts a code graph with
Tree-sitter (Python, TypeScript, Go), embeds every symbol and writes the result
to Postgres.

The schema is owned by `apps/api`: the table definitions and Alembic migrations
live there, and the worker imports the models from it.

The pipeline can be started two ways: from this package's CLI, described below,
or through the API's `POST /ingest`, which imports this package and runs the
same code inside the API process. That is what the web UI uses.

## Setup

From `apps/worker`:

```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ../../packages/shared -e ../api -e ".[dev]"
Copy-Item .env.example .env
```

```sh
# macOS / Linux
python -m venv .venv
source .venv/bin/activate
pip install -e ../../packages/shared -e ../api -e ".[dev]"
cp .env.example .env
```

The install pulls in PyTorch (via sentence-transformers), so it is large. The
embedding model itself (about 90 MB) is downloaded on first run.

Before the first ingest, start Postgres and create the tables:

```sh
docker compose up -d postgres          # repo root
alembic upgrade head                   # apps/api, with its venv active
```

## Ingesting a repository

```sh
python -m worker.ingest https://github.com/owner/repo
```

```
[1/5] Cloning https://github.com/owner/repo
[2/5] Parsing source files
[3/5] Resolving imports, calls and inheritance
[4/5] Embedding 159 symbols
[5/5] Writing to Postgres
Done in 21.4s: 15 files, 159 symbols, 180 edges.
```

**Each run replaces the previous one.** The database holds one repository at a
time: the tables have no repo column, so the write step truncates `files`,
`symbols` and `edges` and reloads them in a single transaction. If a run fails
at any step, the previous data is left untouched.

`--keep-clone` leaves the clone on disk instead of deleting it.

## What gets stored

| Table     | Contents                                                                 |
| --------- | ------------------------------------------------------------------------ |
| `files`   | One row per source file: path, language, SHA-256 of the content, line count, and the full source text (the API cuts snippets from it) |
| `symbols` | Modules, functions, classes and methods, with line range, signature and a 384-dimension embedding |
| `edges`   | `calls`, `imports` and `inherits` relationships between symbols          |

Conventions worth knowing when querying:

- **Every file has one `module` symbol** named after its path. Import edges
  start from it, and so do calls made at the top level of a file.
- **Methods are named `Class.method`**, nested functions `outer.inner`.
- **"Class" includes the nearest equivalent per language**: TypeScript
  interfaces and abstract classes, Go named types. TypeScript `implements` and
  Go struct or interface embedding are stored as `inherits`.
- **Line ranges are 1-based and inclusive**, and include Python decorators.
- **`loc` counts every line**, blank lines and comments included.

## How resolution works, and its limits

Edges are resolved from syntax alone. There is no type inference.

A call becomes an edge when its target can be identified by name:

- a bare name defined in the file, in an enclosing function, in the same Go
  package, or imported
- `self.f()`, `cls.f()`, `this.f()`, a call on a Go method's own receiver, and
  `super().f()`, including methods inherited from base classes
- `module.f()` through an imported module, namespace or Go package
- `Class.f()` on a known class

Everything else is dropped rather than guessed. In practice that means calls on
values whose type is not visible in the syntax (`user.save()`, `items.append()`)
produce no edge, so the call graph is precise but incomplete.

Imports resolve only to files inside the repository. Standard-library and
third-party imports produce no edge. Known gaps:

- TypeScript path aliases from `tsconfig.json` are not followed; only relative
  imports resolve.
- A repository file named like a standard-library module (`json.py` in a
  directory that is not a package) will be taken as the target of `import json`.
- Only `.ts`, `.tsx`, `.mts` and `.cts` count as TypeScript; plain JavaScript is
  not parsed.

Skipped during discovery: hidden directories, `node_modules`, `vendor`,
`__pycache__`, `venv`, `dist`, symlinks, files over `MAX_FILE_BYTES`, and files
containing NUL bytes.

## Commands

Run from `apps/worker` with the venv active.

| Command                               | Does                          |
| ------------------------------------- | ----------------------------- |
| `python -m worker.ingest <repo_url>`  | Run the ingestion pipeline (`atlas-ingest` also works) |
| `pytest`                              | Run tests                     |
| `ruff check .`                        | Lint                          |

The tests need neither Postgres nor network access. They run the extractors and
the resolver against `tests/fixtures/sample_repo`.

## Layout

```
worker/
  ingest.py        CLI entry point
  pipeline.py      File discovery and the five pipeline steps
  clone.py         GitHub URL validation and shallow clone (dulwich)
  extract/         Tree-sitter extraction, one module per language
    types.py       Symbol, Import, Call, FileExtraction
    base.py        Tree walker shared by the language extractors
  resolve.py       Imports, calls and inheritance -> edges
  embed.py         sentence-transformers wrapper
  store.py         Writes files, symbols and edges
  config.py        Settings, loaded from the environment and .env
tests/
  fixtures/sample_repo/   Small Python, TypeScript and Go project
```

## Environment

| Variable               | Default                                                 | Purpose |
| ---------------------- | ------------------------------------------------------- | ------- |
| `DATABASE_URL`         | `postgresql+psycopg://atlas:atlas@localhost:5432/atlas` |         |
| `CLONE_DIR`            | OS temp directory (`/tmp` on Linux)                     | Where repositories are cloned |
| `GITHUB_TOKEN`         | unset                                                   | Needed only for private repositories |
| `EMBEDDING_MODEL`      | `sentence-transformers/all-MiniLM-L6-v2`                | Changing it requires a matching vector size in the schema |
| `EMBEDDING_BATCH_SIZE` | `64`                                                    |         |
| `MAX_FILE_BYTES`       | `1000000`                                               | Larger files are skipped |
| `LOG_LEVEL`            | `INFO`                                                  |         |
