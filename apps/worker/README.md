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

Embeddings run the all-MiniLM-L6-v2 model with ONNX Runtime rather than
PyTorch, which keeps the install and its memory small. The model's ONNX export
(about 90 MB) is downloaded on first run.

Before the first ingest, start Postgres and create the tables:

```sh
docker compose up -d postgres          # repo root
alembic upgrade head                   # apps/api, with its venv active
```

## Adding sources

```sh
python -m worker.ingest https://github.com/owner/repo            # a repository
python -m worker.ingest https://en.wikipedia.org/wiki/HMAC       # a Wikipedia article
python -m worker.ingest https://docs.python.org/3/library/hmac.html   # a web page
python -m worker.ingest https://example.org/docs/ --crawl 20     # up to 20 pages of one site
python -m worker.ingest --file book.pdf                          # PDF, EPUB, .txt, .md, .html
```

Sources accumulate. Adding a source that is already present replaces that
source only; the others are untouched. The kind of a link is worked out from
its host (`github.com`, `*.wikipedia.org`, anything else is a web page).

### Documents

Web pages, articles and files are not parsed as code. Their readable text is
extracted, re-flowed to lines of at most 100 characters and cut into passages
of about 1,000 characters under their headings. Each passage is stored as a
symbol of kind `section`, so search, answers and `[path:start-end]` citations
work on documents exactly as they do on code.

| Source | How the text is obtained | Stored under |
| ------ | ------------------------ | ------------ |
| Web page | The page's article text, without navigation or ads (trafilatura) | `web/<host>/<path>` |
| Wikipedia | The official API's plain-text extract, with section headings | `wikipedia/<lang>/<title>` |
| Crawl | Breadth-first from the start page, same host only, at most 100 pages and 3 links deep | `web/<host>/<path>` |
| File | PDF text layer (one heading per page), EPUB chapters in reading order, or the file's text | `uploads/<name>` |

Limits worth knowing:

- **Only public web addresses are fetched.** Private, loopback and link-local
  addresses are refused, on the first request and on every redirect, as are
  ports other than 80 and 443. The check resolves the name before the request
  is made; a host that changes its DNS answer between the two could slip
  through, so do not expose ingestion to untrusted users on a network with
  sensitive internal services.
- **The crawler obeys `robots.txt`** and waits half a second between pages.
- **Scanned PDFs are not read**: there is no OCR, so a PDF needs a text layer.
- **Pages that build their content with JavaScript** come back empty, because
  nothing runs the scripts.
- Pages over 5 MB and files over 30 MB are refused.

Only add material you have the right to copy.

## Ingesting a repository

```sh
python -m worker.ingest https://github.com/owner/repo
```

Repository files are stored under `owner/repo/`, so two repositories can hold
a file with the same relative path.

```
[1/5] Cloning https://github.com/owner/repo
[2/5] Parsing source files
[3/5] Resolving imports, calls and inheritance
[4/5] Embedding 159 symbols
[5/5] Writing to Postgres
Done in 21.4s: 15 files, 159 symbols, 180 edges.
```

Each run writes its source in a single transaction. If it fails at any step,
nothing changes: an earlier copy of the same source, and every other source,
stay as they were.

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
  documents.py     Text documents -> passages with line ranges
  sources.py       Loaders: web page, Wikipedia, crawl, uploaded file
  fetch.py         HTTP fetching restricted to public addresses; robots.txt
  embed.py         all-MiniLM-L6-v2 on ONNX Runtime (shared per process)
  store.py         Writes a source with its files, symbols and edges
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
| `EMBEDDING_BATCH_SIZE` | `16`                                                    | Peak memory grows about 18 MB per text in a batch |
| `MAX_FILE_BYTES`       | `1000000`                                               | Larger files are skipped |
| `LOG_LEVEL`            | `INFO`                                                  |         |
