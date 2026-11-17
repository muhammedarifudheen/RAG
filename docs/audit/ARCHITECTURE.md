# Atlas architecture (Phase 0: discovery)

Read-only map of the system at commit `b5af76a` (`origin/main`, 2026-11-17). Every location is
`file:line` at that commit; endpoint and setting tables are generated from the running code, not
typed. Nothing here is a measurement of quality: that is Phase 1. Anything not verified is marked
**unverified**.

## 1. What it is

A retrieval-augmented question answerer over a small knowledge base built from GitHub repositories,
web pages, Wikipedia articles and uploaded documents. Answers carry `[path:start-end]` citations.
Public deployment: static site on GitHub Pages, API on Render's free plan (512 MB), models called
over HTTP (Gemini by default on the public server).

| | |
| --- | --- |
| Languages | Python 3.11+ (API, worker), TypeScript (Next.js 14 web app, shared types) |
| Size | `apps/api/app` 88 files / 16.1k lines; `apps/worker/worker` 22 / 3.1k; `apps/web/src` 44 / 8.4k; `apps/api/evals` 11 / 2.1k; `apps/api/tests` 45 / 9.1k |
| Manifests | `package.json`, `pnpm-workspace.yaml`, `apps/web/package.json`, `packages/shared/package.json`, `apps/api/pyproject.toml`, `apps/worker/pyproject.toml`, `docker-compose.yml`, `render.yaml` |
| Entrypoints | API: `apps/api/app/main.py` (`uvicorn app.main:app`); worker CLI: `python -m worker.ingest <url>` (`apps/worker/worker/ingest.py`); web: `apps/web` (`next dev` / static export); server image: `deploy/server/start.sh` |

```
apps/api      FastAPI service: /ask, /search, /ingest, /health*, analytics, MCP, OpenAI-compatible API
  app/assistant   answer generation: prompts, council of models, contract, research agent, web search
  app/retrieval   ranking, budgets, caches, gate, zero-retrieval monitor, cross-encoder (off)
  app/services    search, knowledge graph, analytics, source health, webhooks, freshness
  app/routers     HTTP layer     app/models  SQLAlchemy tables     migrations/  Alembic
  evals/          eval harness + golden sets          tests/  pytest (needs Postgres for ~150 tests)
apps/worker   ingestion: source adapters, extractors/chunkers, embedder, store
apps/web      Next.js UI (ingest, chat, graph, health, analyse, insights)
packages/shared   API types (TypeScript)
deploy/server     Render image: Postgres + API in ONE container, starter sources baked in
.github/workflows CI, deploy, pages, nightly/weekly jobs
```

## 2. HTTP endpoints (55, generated)

| Method | Path | Handler | Purpose |
| --- | --- | --- | --- |
| POST | `/admin/check` | `apps/api/app/routers/sources.py:80` | Check the admin password |
| GET | `/analytics` | `apps/api/app/routers/analytics.py:57` | Query the answer log |
| POST | `/ask` | `apps/api/app/routers/search.py:88` | Ask a question about the knowledge base |
| POST | `/attachments` | `apps/api/app/routers/chat.py:36` | Read a file's text, to attach to a question |
| GET | `/config` | `apps/api/app/routers/sources.py:59` | What this deployment allows |
| GET | `/docs` | `fastapi (built-in)` | OpenAPI / docs |
| GET | `/docs/oauth2-redirect` | `fastapi (built-in)` | OpenAPI / docs |
| GET | `/export/analytics.csv` | `apps/api/app/routers/analytics.py:79` | An analytics query as CSV |
| GET | `/export/audit.md` | `apps/api/app/routers/integrations.py:182` | The knowledge audit as Markdown |
| GET | `/export/qa.jsonl` | `apps/api/app/routers/integrations.py:155` | Export the answers as JSONL, for evaluation |
| POST | `/feedback` | `apps/api/app/routers/analytics.py:35` | Rate an answer |
| GET | `/file` | `apps/api/app/routers/files.py:32` | Source and symbols of one file |
| GET | `/graph` | `apps/api/app/routers/graph.py:18` | Call graph around a file |
| GET | `/graph/files` | `apps/api/app/routers/files.py:18` | Dependency graph between files |
| GET | `/health` | `apps/api/app/routers/health.py:33` | Code health report |
| POST | `/health` | `apps/api/app/routers/health.py:79` | Audit the knowledge base |
| GET | `/health/reranker` | `apps/api/app/routers/health.py:219` | The cross-encoder reranker: loaded, on what, and how fast |
| GET | `/health/retrieval` | `apps/api/app/routers/health.py:194` | Zero-retrieval detector: how many recent queries retrieved nothing |
| GET | `/health/sources` | `apps/api/app/routers/health.py:149` | Live health of each source, with actions |
| POST | `/health/sources/{source_id}/candidates` | `apps/api/app/routers/health.py:164` | Suggest primary sources behind a source |
| GET | `/healthz` | `apps/api/app/routers/health.py:143` | Liveness probe |
| POST | `/hooks/github` | `apps/api/app/routers/integrations.py:105` | GitHub push: re-index the repository |
| POST | `/ingest` | `apps/api/app/routers/ingest.py:185` | Add a source from a link |
| POST | `/ingest/upload` | `apps/api/app/routers/ingest.py:220` | Add a source from an uploaded file |
| GET | `/keys` | `apps/api/app/routers/keys.py:28` | List the API keys |
| POST | `/keys` | `apps/api/app/routers/keys.py:34` | Make an API key |
| DELETE | `/keys/{key_id}` | `apps/api/app/routers/keys.py:47` | Revoke an API key |
| GET | `/kg` | `apps/api/app/routers/kg.py:41` | The knowledge graph around a node |
| GET | `/kg/ask` | `apps/api/app/routers/kg.py:114` | A question about the graph, in words |
| GET | `/kg/node` | `apps/api/app/routers/kg.py:93` | A node, for the graph's side panel |
| GET | `/kg/overview` | `apps/api/app/routers/kg.py:105` | The knowledge graph, for drawing |
| GET | `/kg/path` | `apps/api/app/routers/kg.py:82` | The shortest path between two nodes |
| GET | `/kg/related` | `apps/api/app/routers/kg.py:63` | Callers, dependencies, contradictions or successors |
| GET | `/mcp` | `apps/api/app/routers/mcp.py:74` | MCP: no server-initiated stream |
| POST | `/mcp` | `apps/api/app/routers/mcp.py:80` | MCP (Streamable HTTP): JSON-RPC requests |
| GET | `/openapi.json` | `fastapi (built-in)` | OpenAPI / docs |
| GET | `/redoc` | `fastapi (built-in)` | OpenAPI / docs |
| GET | `/search` | `apps/api/app/routers/search.py:63` | Semantic search over the knowledge base |
| POST | `/shares` | `apps/api/app/routers/chat.py:78` | Share a chat by link |
| GET | `/shares/{share_id}` | `apps/api/app/routers/chat.py:98` | Read a shared chat |
| GET | `/sources` | `apps/api/app/routers/sources.py:25` | List what has been ingested |
| DELETE | `/sources/{source_id}` | `apps/api/app/routers/sources.py:131` | Remove a source |
| PATCH | `/sources/{source_id}` | `apps/api/app/routers/sources.py:107` | Set how much a source counts |
| POST | `/sources/{source_id}/preview` | `apps/api/app/routers/versions.py:87` | What re-ingesting a source would change |
| POST | `/sources/{source_id}/rollback` | `apps/api/app/routers/versions.py:64` | Restore a kept version of a source |
| GET | `/sources/{source_id}/versions` | `apps/api/app/routers/versions.py:36` | A source's kept versions |
| GET | `/v1/analytics` | `apps/api/app/routers/openai.py:309` | analytics.query(metric, window, filter) |
| POST | `/v1/chat/completions` | `apps/api/app/routers/openai.py:60` | OpenAI-compatible: a chat completion |
| POST | `/v1/embeddings` | `apps/api/app/routers/openai.py:254` | OpenAI-compatible: embeddings |
| GET | `/v1/graph` | `apps/api/app/routers/openai.py:280` | The knowledge graph around a node |
| GET | `/v1/health` | `apps/api/app/routers/openai.py:299` | The knowledge base's live health |
| GET | `/v1/models` | `apps/api/app/routers/openai.py:49` | OpenAI-compatible: the models |
| GET | `/webhooks` | `apps/api/app/routers/integrations.py:45` | List the webhooks |
| POST | `/webhooks` | `apps/api/app/routers/integrations.py:62` | Add a webhook |
| DELETE | `/webhooks/{webhook_id}` | `apps/api/app/routers/integrations.py:88` | Remove a webhook |

_55 endpoints._

## 3. Ingest pipeline

| Step | Where |
| --- | --- |
| Kind detection (repo, Wikipedia, web, crawl, upload) | `apps/worker/worker/sources.py:61` `detect_kind` |
| Source adapters | repo clone (dulwich) `pipeline.py:208` `ingest_directory`; `load_web` `sources.py:134`; `load_wikipedia` `:181`; `load_crawl` `:243`; `load_upload` `:415` (PDF, EPUB, DOCX, text, code) |
| Fetch safety | `worker/fetch.py:40` `check_public_url` (public hosts only), `MAX_BYTES` 5 MB `:21`, `MAX_REDIRECTS` 5 `:22` |
| HTML to text | `sources.py:104` `html_to_document` (trafilatura); `:81` `flatten_definitions` keeps Sphinx API entries |
| Chunker, prose | `worker/documents.py:106` `build_extraction`: re-flows to 100-char lines (`:19`), passages of about 1000 chars (`:22`) cut at headings and block boundaries; each passage a `section` symbol with its heading path |
| Chunker, code | tree-sitter extractors `worker/extract/python.py:9`, `typescript.py`, `go.py` on `extract/base.py:20`: one symbol per function, class, method, plus a module symbol |
| Edges | `worker/resolve.py:41` `resolve` (call/import graph) |
| Embedder | `worker/embed.py:32` `OnnxModel` (all-MiniLM-L6-v2 via ONNX Runtime, 384 dims, 256-token limit); `symbol_text` `:24`, `MAX_CHARS` 2000 `:15`; batch 16 (`worker/config.py`) |
| Incremental ingest | `pipeline.py:137`: a file with an unchanged content hash reuses its embeddings |
| Near-duplicate detection | `worker/minhash.py`: 64 permutations, Jaccard threshold 0.7, minimum 20 shingles (`:15`, `:19`, `:21`); later copies point at the canonical (`symbols.duplicate_of`) |
| Index writer | `worker/store.py:28` `store_source`; versions `worker/versions.py:31` `snapshot`, `:106` `restore` |
| Cache invalidation on ingest | `api/app/routers/ingest.py` `_work` calls `retrieval.state.bump()` (`api/app/retrieval/state.py:31`) |

## 4. Retrieval and answer pipeline (`POST /ask`, `apps/api/app/routers/search.py:110`)

| Stage | Where |
| --- | --- |
| Mode and route | `assistant/modes.py` `classify_mode` (called `search.py:269`); `assistant/router.py:126` `classify` (route from wording and top similarity; `SOURCES_SCORE` 0.45 `:75`) |
| Query planning (rewrite, keywords, HyDE, variant; at most 4) | `assistant/service.py:658` `plan_queries`, called with a time budget at `search.py:303`; parsing `assistant/planner.py:20` |
| Embedding of the query | `api/app/embedding.py:20` `LocalEmbedder.embed`; LRU of 512 keyed by the normalised text (`:17`) |
| Vector search (HNSW, cosine) | `services/search.py` `search_symbols`; `SET LOCAL hnsw.ef_search = max(2*limit, 64)` at `:68` |
| Keyword search | `services/search.py:80` `keyword_symbols`: Postgres full-text search (`to_tsquery` OR-joined `:95`, `ts_rank_cd` `:97`) on `symbols.search` (GIN index, migration `20261030_1200_0006`). **Not BM25.** |
| Hybrid + fusion | `services/search.py:150` `hybrid_search`: vector and keyword top 20 (`CANDIDATES` `:52`), reciprocal-rank fusion (`assistant/planner.py:42` `fuse`, `RRF_K` 60 `:15`), then MMR `:203` `diversify` (lambda 0.7) |
| Per-variant fusion + retrieval cache | `search.py:327` `retrieve` (cache key query+limit+as_of+kb_version, 1 h; `retrieval/state.py:23`); `search.py:360` `fuse` over the variants |
| Relevance judge + listwise ranker | `assistant/service.py:826` `judge_chunks` (one small-model call per excerpt, 0-10), `:890` `rank_chunks`; applied `assistant/rerank.py:91` `rerank` (cut-off 4); budgeted at `search.py:420` |
| Cross-encoder reranker | `retrieval/reranker.py:289` `rerank` (bge-reranker-v2-m3 ONNX): **present, off** (`ATLAS_RERANK=off`, `config.py`); `/health/reranker` |
| Relevance gate / low-confidence path | `retrieval/gate.py:33` `summarise`, `:42` `is_low`, `:48` `low_confidence_pick`; wired `search.py:426-429` (path off by default) |
| Weighted final score | `retrieval/scoring.py:105` `rank`: 0.45 rerank + 0.20 RRF + 0.15 trust + 0.10 freshness + 0.10 source record (`:18`); **off** by default (`RETRIEVAL_WEIGHTED_RANK`); shadow-logged at `search.py:482` |
| Adaptive top-k | `retrieval/topk.py:23` (3 / 5 / 8, cap 8) |
| Budgets and degradation | `retrieval/budget.py:27` `Trace`, `:48` `run_stage`, `:123` `Budget` (stages `:92`); planner and judge fall back, search falls back vector to keyword (`services/search.py:150`) |
| Zero-retrieval monitor | `retrieval/monitor.py:52`; record at `search.py:539`; `GET /health/retrieval` |
| Prompt assembly | `assistant/prompt.py:520` `conversation` (excerpts as `<context>` blocks `:267` `context_blocks`), `:506` `system_prompt`, `:247` `strict_prompt`, `:257` `strict_message`; plain path `api/app/llm.py:70` `build_prompt` |
| Answer generation | `assistant/service.py:330` `respond` (council of models, merge, streaming); `:391` `_answer_events` |
| Answer contract | `assistant/contract.py:31` states, `:119` `derive_state`, `:230` `evidence_gap`, `:292` `apply`; banned-phrase guard `:88` `BannedGuard`, regeneration `service.py:330` |
| Output safety | `api/app/security.py:45` `injection` (input filter), `:56` `_SECRETS`, `:80` `redact`, `:100` `Redactor` (streamed output); applied in `service.py` `respond` |
| Citation verification | `services/search.py` `extract_citations`, `tidy_citations` (a citation is `verified` if its lines were among the excerpts shown) |
| Confidence / freshness / footer | `assistant/confidence.py`; `services/freshness.py`; `service.py:1847` `with_footer` |
| Answer cache | `assistant/cache.py:20` `TTLCache`; `service.py:300` (256 entries, 24 h; "absent" answers 1 h, `routers/search.py` `_remember`) |
| Per-query records | `routers/search.py:495` `retrieval {...}` log line; `service.py:1904` `_log_answer`; `retrieval/monitor.py:87` `retrieval_summary`; `services/knowledge.py:46` `log_answer` (table `answer_log`) |

Research agent (multi-step tool loop, up to 6 calls: search, read, note, graph, analytics, health,
fetch, external MCP tools): `assistant/agent.py`, `services/agent_tools.py`, `assistant/mcp_client.py`.
Web search before non-grounded answers: `assistant/web.py`.

## 5. Prompt, contract and refusal files

| Item | Where |
| --- | --- |
| System prompt (assistant) | `assistant/prompt.py:169` `SYSTEM` |
| Plain-path system prompt | `api/app/llm.py:17` `SYSTEM_PROMPT` |
| Strict prompt | `prompt.py:220` `STRICT_ANSWER`, `strict_prompt` `:247` |
| Epistemic-state rules | `prompt.py:21` `EPISTEMIC` (+ `EPISTEMIC_FORMAT`) |
| Low-confidence note | `retrieval/gate.py:24` `LOW_CONFIDENCE_NOTE` |
| Answer contract (5 states, evidence-gap report, labels) | `assistant/contract.py` |
| Refusal strings | `prompt.py:219` `NOT_IN_SOURCES` (still defined; no longer asked of the model); `contract.py:35` `BANNED_PHRASES`; legacy detection in `service.py:1784` `_with_state` and `apps/web/src/components/Answer.tsx:869` |
| Injection refusal | `routers/search.py:161` (via `security.py:45`; neutral refusal, recorded) |

## 6. Eval harness

| | |
| --- | --- |
| Runner | `apps/api/evals/run_evals.py` (stdlib only): `search` mode (GET /search) and `ask` mode (POST /ask) |
| Metrics | `evals/metrics.py`: hit@k, recall@k, MRR, nDCG@k (file-deduped, capped at 1), citation precision, coverage, decline detection; `evals/contract_metrics.py`: `dead_end_rate`, `unsupported_claim_rate`; run_evals adds degraded_rate, latency p50/p95, first-token |
| Gates | `--min`, `--max`, `--baseline --max-drop`, `--contract-gate` (`run_evals.py:310`, `:357`) |
| Golden sets | `evals/golden/golden_set.jsonl` (40, keyed by path), `out_of_corpus.jsonl` (10), `gate.jsonl` (24), `live.jsonl` (12), `atlas.jsonl` (10), `sources.jsonl` (12 source probes) |
| Other tools | `calibrate_gate.py`, `verify_sources.py`, `compare.py`, `rerank.py` (offline cross-encoder) |
| CI wiring | `ci.yml`: ruff, pytest (Postgres service), web lint/typecheck/e2e; the harness's own logic is unit-tested. `contract-eval.yml`: the gate against the live server, weekly and on demand. **No workflow runs the golden-set retrieval eval on a build.** |

## 7. Storage and persistence

| Store | What | Guarantee |
| --- | --- | --- |
| Postgres 16 + pgvector | sources, files, symbols (+ embedding, `search` tsvector), edges, KG, answer log, audit, versions, webhooks, shares, API keys | **Public server: ephemeral.** `deploy/server/start.sh` runs Postgres inside the API container; each start loads the dump baked at image build (`bake.sh`, `SEED_SOURCES`). Nothing written at runtime survives a restart or deploy. Local/compose: a Docker volume. |
| Vector index | HNSW `ix_symbols_embedding_hnsw` (cosine) | m=16, ef_construction=200 (migration `20261030_1200_0006` `:68-69`); the ORM model (`models/code_graph.py:86`) declares the index without these parameters (drift, migration is authoritative). `ef_search` set per query. |
| Keyword index | GIN `ix_symbols_search` on a trigger-maintained tsvector (same migration) | with the database |
| Caches | answer, verdict (relevance judge), retrieval, embedding LRU, reranker latency | **In process memory only**; cleared on restart; keyed on `kb_version` (`retrieval/state.py:40`) |
| Zero-retrieval window | last 100 queries | in memory, per process |
| Answer log | table `answer_log` | ephemeral with the database; `.github/workflows/knowledge-log.yml` exports it **every 6 hours** to the `knowledge-log` branch, reloaded at start (`start.sh`). Up to 6 hours of log can be lost. |
| Log sink | none for per-query logs: the `retrieval {...}` and `retrieval_summary` lines go to the process log (Render's log stream) | a pluggable external sink exists only on an unpushed branch, **not on main** |

## 8. Health and observability

`GET /healthz` (liveness), `GET /health` (code health), `POST /health` (knowledge audit, admin),
`GET /health/sources`, `GET /health/reranker`, `GET /health/retrieval`, `GET /v1/health`,
`GET /analytics` (answer-log queries by metric; `routers/analytics.py:57`),
webhooks (`services/webhooks.py`; events `ingest`, `query`, `gap`, `health`),
per-query log lines (section 4), request log (`middleware.py:15`), audit trail (`services/audit.py`).
Scheduled: `keep-awake.yml` (10 min), `knowledge-audit.yml` (weekly), `knowledge-log.yml` (6 h),
`latency-report.yml` (weekly), `contract-eval.yml` (weekly).

## 9. Configuration surface (119 API settings, generated)

Env var = setting name upper-cased (`pydantic-settings`, `apps/api/app/config.py`). Worker settings
(`apps/worker/worker/config.py`): `DATABASE_URL`, `LOG_LEVEL`, `CLONE_DIR`, `GITHUB_TOKEN`,
`EMBEDDING_MODEL`, `EMBEDDING_BATCH_SIZE` (16), `MAX_FILE_BYTES` (1,000,000), and a few more.
Image/deploy: `SEED_SOURCES`, `ADMIN_TOKEN`, `GEMINI_API_KEY`, `CORS_ORIGINS`, `PORT` (`render.yaml`,
`deploy/server/Dockerfile`, `start.sh`).

| Env var | Default | Controls | Line |
| --- | --- | --- | --- |
| `DATABASE_URL` | `'postgresql+psycopg://atlas:atlas@localhost:5432/atlas'` |  | `config.py:9` |
| `CORS_ORIGINS` | `['http://localhost:3000']` |  | `config.py:10` |
| `LOG_LEVEL` | `'INFO'` |  | `config.py:11` |
| `EMBEDDING_MODEL` | `'sentence-transformers/all-MiniLM-L6-v2'` | Must match the model the worker embedded the symbols with. | `config.py:14` |
| `SNIPPET_MAX_LINES` | `80` | Longest snippet returned for one symbol, and sent to Claude, in lines. | `config.py:16` |
| `LLM_PROVIDER` | `'anthropic'` | Which model provider answers /ask. | `config.py:19` |
| `GEMINI_API_KEY` | `None` |  | `config.py:21` |
| `GEMINI_MODELS` | `'gemini-flash-latest,gemini-3.5-flash,gemini-flash-lite-late` | Tried in order; the next is used when one is overloaded or over quota. | `config.py:23` |
| `GEMINI_MAX_TOKENS` | `(set via env)` |  | `config.py:24` |
| `ANTHROPIC_API_KEY` | `None` | Unset means the Anthropic SDK resolves credentials itself (environment or profile). | `config.py:27` |
| `ANTHROPIC_MODEL` | `'claude-opus-5-5'` |  | `config.py:28` |
| `ANTHROPIC_EFFORT` | `'medium'` |  | `config.py:29` |
| `ANTHROPIC_MAX_TOKENS` | `(set via env)` |  | `config.py:30` |
| `GROQ_API_KEY` | `None` | console.groq.com/keys | `config.py:36` |
| `GROQ_MODELS` | `'openai/gpt-oss-120b,openai/gpt-oss-20b'` |  | `config.py:37` |
| `OPENROUTER_API_KEY` | `None` | openrouter.ai/keys | `config.py:38` |
| `OPENROUTER_MODELS` | `'auto'` | "auto": every free model in OpenRouter's public catalogue (it changes often). | `config.py:40` |
| `MISTRAL_API_KEY` | `None` | console.mistral.ai/api-keys | `config.py:41` |
| `MISTRAL_MODELS` | `'mistral-large-latest,mistral-medium-latest,codestral-latest` |  | `config.py:42` |
| `CEREBRAS_API_KEY` | `None` | cloud.cerebras.ai | `config.py:43` |
| `CEREBRAS_MODELS` | `'gpt-oss-120b,llama-3.3-70b,qwen-3-32b'` |  | `config.py:44` |
| `GITHUB_MODELS_TOKEN` | `None` | A GitHub token with the "Models" permission (github.com/settings/tokens). | `config.py:46` |
| `GITHUB_MODELS_MODELS` | `'openai/gpt-4.1,openai/gpt-4.1-mini,meta/Llama-3.3-70B-Instr` |  | `config.py:47` |
| `CLOUDFLARE_ACCOUNT_ID` | `None` | dash.cloudflare.com → Workers AI | `config.py:50` |
| `CLOUDFLARE_API_TOKEN` | `None` |  | `config.py:51` |
| `CLOUDFLARE_MODELS` | `'@cf/meta/llama-3.3-70b-instruct-fp8-fast,@cf/qwen/qwq-32b,@` |  | `config.py:52` |
| `HUGGINGFACE_API_KEY` | `None` | huggingface.co/settings/tokens | `config.py:56` |
| `HUGGINGFACE_MODELS` | `'meta-llama/Llama-3.3-70B-Instruct,Qwen/Qwen2.5-72B-Instruct` |  | `config.py:57` |
| `SAMBANOVA_API_KEY` | `None` | cloud.sambanova.ai | `config.py:60` |
| `SAMBANOVA_MODELS` | `'DeepSeek-V3.2,gpt-oss-120b,Meta-Llama-3.3-70B-Instruct,Mini` |  | `config.py:61` |
| `DEEPSEEK_API_KEY` | `None` | platform.deepseek.com (paid, very cheap) | `config.py:62` |
| `DEEPSEEK_MODELS` | `'deepseek-chat,deepseek-reasoner'` |  | `config.py:63` |
| `NVIDIA_API_KEY` | `None` | build.nvidia.com | `config.py:64` |
| `NVIDIA_MODELS` | `'nvidia/nemotron-3.5-super-vl-120b-a12b,nvidia/nemotron-3-ul` |  | `config.py:65` |
| `COHERE_API_KEY` | `None` | dashboard.cohere.com/api-keys | `config.py:69` |
| `COHERE_MODELS` | `'command-a-03-2025'` |  | `config.py:70` |
| `TOGETHER_API_KEY` | `None` | api.together.ai | `config.py:71` |
| `TOGETHER_MODELS` | `'meta-llama/Llama-3.3-70B-Instruct-Turbo-Free'` |  | `config.py:72` |
| `POLLINATIONS_TEXT` | `True` | Free without any key. | `config.py:74` |
| `POLLINATIONS_TEXT_MODELS` | `'openai-fast'` |  | `config.py:75` |
| `HORDE_ENABLED` | `True` | AI Horde: volunteers' machines; anonymous use ("0000000000") is free but slow. | `config.py:77` |
| `HORDE_API_KEY` | `(set via env)` |  | `config.py:78` |
| `HORDE_TEXT_MODELS` | `'google/gemma-4-31b'` |  | `config.py:79` |
| `HORDE_IMAGE_MODELS` | `'AlbedoBase XL (SDXL),Juggernaut XL,Deliberate'` | One picture agent per model, drawn in parallel. Anonymous requests wait behind | `config.py:82` |
| `ASSISTANT_MODELS_PER_PROVIDER` | `2` | How many of one provider's models to try before moving to the next provider. | `config.py:85` |
| `ASSISTANT_BEST_ORDER` | `'claude,gemini,deepseek,openrouter,github,mistral,cerebras,g` | "Best model + fallbacks" order, strongest first. | `config.py:87` |
| `ASSISTANT_COUNCIL_SIZE` | `12` | The council: this many agents answer each question in parallel and one model | `config.py:93` |
| `ASSISTANT_COUNCIL_GRACE` | `4.0` | Once two agents have answered, wait this many more seconds for the rest. | `config.py:95` |
| `ASSISTANT_COUNCIL_MAX_WAIT` | `35.0` | And never wait longer than this for the panel (the first answer is waited for). | `config.py:97` |
| `ASSISTANT_FAST_MERGERS` | `'groq,cerebras'` | Services that merge the drafts first when one of their models answered: the quickest, | `config.py:100` |
| `ASSISTANT_MERGE_BY_SPEED` | `True` | After those, the agents that answered merge in order of how quickly they wrote | `config.py:103` |
| `ASSISTANT_MERGE_DRAFTS` | `5` | At most this many drafts go to the merge (the best-suited agents' first). | `config.py:105` |
| `ASSISTANT_WEB_SEARCH` | `True` | Search the web before every answer (except small talk) and give every agent the | `config.py:109` |
| `WEB_NEWS` | `True` | Google News and Wikipedia need no key; Tavily (1,000 free searches a month) and | `config.py:112` |
| `WEB_WIKIPEDIA` | `True` |  | `config.py:113` |
| `TAVILY_API_KEY` | `None` | https://app.tavily.com | `config.py:114` |
| `BRAVE_API_KEY` | `None` | https://brave.com/search/api | `config.py:115` |
| `WEB_MAX_WAIT` | `5.0` |  | `config.py:116` |
| `ASSISTANT_QUERY_PLANNER` | `True` | Before a knowledge-base search, a fast model plans several queries (the question, | `config.py:119` |
| `ASSISTANT_RERANKER` | `True` | Then fast models judge each candidate excerpt's relevance (0-10, the user's judge | `config.py:122` |
| `ASSISTANT_RERANK_CUTOFF` | `4` |  | `config.py:123` |
| `ASSISTANT_TOP_K` | `5` | Excerpts given to the answer model when the question does not say. | `config.py:125` |
| `RETRIEVAL_ADAPTIVE_TOP_K` | `True` | The retrieval core (app/retrieval): 3, 5 or 8 excerpts by the kind of question when | `config.py:131` |
| `RETRIEVAL_CONFIDENCE_GATE` | `4` | The relevance gate: when the judge's best score is under `retrieval_confidence_gate` | `config.py:135` |
| `RETRIEVAL_LOW_CONFIDENCE` | `False` |  | `config.py:136` |
| `RETRIEVAL_ALERT_THRESHOLD` | `0.2` | The zero-retrieval detector (app/retrieval/monitor.py): more than `threshold` of the last | `config.py:140` |
| `RETRIEVAL_ALERT_WINDOW` | `100` |  | `config.py:141` |
| `RETRIEVAL_ALERT_MIN_SAMPLES` | `10` |  | `config.py:142` |
| `RETRIEVAL_WEIGHTED_RANK` | `False` | off: it lowered top-1 hits in the eval | `config.py:143` |
| `RETRIEVAL_PLAN_BUDGET` | `6.0` |  | `config.py:144` |
| `RETRIEVAL_JUDGE_BUDGET` | `12.0` |  | `config.py:145` |
| `RETRIEVAL_CACHE` | `True` |  | `config.py:146` |
| `ATLAS_RERANK` | `'off'` | A cross-encoder reranks the top 20 candidates and keeps 5 (app/retrieval/reranker.py). | `config.py:151` |
| `ATLAS_RERANK_MODEL` | `'BAAI/bge-reranker-v2-m3'` |  | `config.py:152` |
| `ATLAS_RERANK_ONNX_REPO` | `'onnx-community/bge-reranker-v2-m3-ONNX'` |  | `config.py:153` |
| `ATLAS_RERANK_PRECISION` | `'fp32'` | or int8 | `config.py:154` |
| `ATLAS_RERANK_MAX_LENGTH` | `512` |  | `config.py:155` |
| `ATLAS_RERANK_TIMEOUT_MS` | `150` |  | `config.py:156` |
| `ATLAS_RERANK_WARMUP_RUNS` | `5` | At start the model is loaded and run this many times on dummy pairs, so the first real | `config.py:161` |
| `BUDGET_REWRITE_MS` | `40` | The per-query latency budget, in milliseconds per stage (app/retrieval/budget.py). | `config.py:168` |
| `BUDGET_EMBED_MS` | `60` |  | `config.py:169` |
| `BUDGET_BM25_MS` | `30` |  | `config.py:170` |
| `BUDGET_VECTOR_MS` | `80` |  | `config.py:171` |
| `BUDGET_FUSE_MS` | `5` |  | `config.py:172` |
| `BUDGET_RERANK_MS` | `150` |  | `config.py:173` |
| `BUDGET_ASSEMBLE_MS` | `20` |  | `config.py:174` |
| `BUDGET_FIRST_TOKEN_MS` | `(set via env)` |  | `config.py:175` |
| `BUDGET_FULL_ANSWER_MS` | `3000` |  | `config.py:176` |
| `BUDGET_ENFORCE` | `''` |  | `config.py:177` |
| `ATLAS_RERANK_P50_LIMIT_MS` | `150.0` |  | `config.py:178` |
| `ATLAS_RERANK_SLOW_STREAK` | `10` |  | `config.py:179` |
| `ASSISTANT_ANSWER_CACHE` | `True` | Reuse answers to repeated questions for a day (see app/assistant/cache.py). | `config.py:181` |
| `ASSISTANT_RESEARCH_AUTO` | `True` | Deep research for questions that look complex, when the user has not chosen. | `config.py:183` |
| `ASSISTANT_JUDGE_SERVICES` | `'nvidia,cerebras,sambanova,mistral,github,groq,gemini'` | The judge's and ranker's services, first to last: about 17 small calls a question, | `config.py:186` |
| `ASSISTANT_MIN_SCORE` | `0.3` | Knowledge-base excerpts less similar than this are not shown to the model. | `config.py:188` |
| `ASSISTANT_MAX_TOKENS` | `(set via env)` |  | `config.py:189` |
| `IMAGE_URL_TEMPLATE` | `'https://image.pollinations.ai/prompt/{prompt}?width=1024&he` | Pictures: a gallery from several services at once. Pollinations needs no key | `config.py:194` |
| `IMAGE_GALLERY_SIZE` | `8` |  | `config.py:198` |
| `IMAGE_MAX_WAIT` | `90.0` |  | `config.py:199` |
| `CLOUDFLARE_IMAGE_MODEL` | `'@cf/black-forest-labs/flux-1-schnell'` |  | `config.py:200` |
| `HUGGINGFACE_IMAGE_MODEL` | `'black-forest-labs/FLUX.1-schnell'` |  | `config.py:201` |
| `TOGETHER_IMAGE_MODEL` | `'black-forest-labs/FLUX.1-schnell-Free'` | Together's free FLUX endpoint, used once TOGETHER_API_KEY is set. | `config.py:203` |
| `GEMINI_IMAGES` | `False` | Gemini's image model has no free quota: on only for a key with billing. | `config.py:205` |
| `GEMINI_IMAGE_MODEL` | `'gemini-2.5-flash-image'` |  | `config.py:206` |
| `ADMIN_TOKEN` | `None` | When set, adding and removing sources needs `Authorization: Bearer <token>`; | `config.py:210` |
| `ADMIN_TOTP_SECRET` | `None` | With this (a base32 secret for an authenticator app), unlocking admin needs its | `config.py:213` |
| `ASSISTANT_GROUNDED` | `False` | Answers only from the knowledge base unless a request asks for more (X-Atlas-Open); | `config.py:216` |
| `API_KEY_RATE_LIMIT_PER_MINUTE` | `(set via env)` | Requests a minute for each API key (X-Atlas-Key). | `config.py:218` |
| `FRESHNESS_CODE_DAYS` | `30` | Freshness: days after ingest before a source is STALE (a third of it is FRESH). | `config.py:221` |
| `FRESHNESS_DOCS_DAYS` | `90` |  | `config.py:222` |
| `FRESHNESS_NEWS_DAYS` | `7` |  | `config.py:223` |
| `ATLAS_WEBHOOKS` | `None` | Integrations. Webhooks set on the server (comma-separated), beside the admin's own, | `config.py:227` |
| `ATLAS_WEBHOOK_SECRET` | `None` |  | `config.py:228` |
| `GITHUB_WEBHOOK_SECRET` | `None` | GitHub's push webhook re-indexes a repository source; deliveries are verified with | `config.py:231` |
| `ATLAS_MCP_SERVERS` | `None` | MCP servers whose read-only tools the AGENT mode may call: comma-separated | `config.py:234` |
| `ATLAS_MCP_TOKEN` | `None` | Sent to them as `Authorization: Bearer`, if set. | `config.py:236` |
| `RATE_LIMIT_PER_MINUTE` | `60` | Requests per client IP per minute; 0 disables. /ask has its own, lower limit | `config.py:240` |
| `ASK_RATE_LIMIT_PER_MINUTE` | `30` |  | `config.py:241` |
| `INGEST_RATE_LIMIT_PER_MINUTE` | `5` |  | `config.py:242` |

## 10. Components: where each lives

| Component | Location | State |
| --- | --- | --- |
| chunker | `worker/documents.py:106` (prose), `worker/extract/*.py` (code) | present |
| embedder | `worker/embed.py:32`, `api/app/embedding.py:20` | present (small model, see missing list) |
| vector_index | migration `20261030_1200_0006:68`, `models/code_graph.py:86` | present |
| bm25_index | `services/search.py:80` (Postgres FTS; GIN) | **stubbed: full-text rank, not BM25** |
| fusion | `assistant/planner.py:42`, `services/search.py:150` | present |
| reranker | `assistant/rerank.py:91` + `service.py:826` (LLM judge); `retrieval/reranker.py:289` (cross-encoder) | judge on; cross-encoder present, **off** |
| prompt_builder | `assistant/prompt.py:520`, `:506` | present |
| answer_contract | `assistant/contract.py` | present |
| refusal_strings | `prompt.py:219`, `contract.py:35` | present (banned, replaced by report) |
| cache | `assistant/cache.py:20`, `retrieval/state.py:23`, `embedding.py:17` | present, in-memory |
| logger | `routers/search.py:495`, `service.py:1904`, `monitor.py:87`, `knowledge.py:46` | present; no durable sink |
| eval_runner | `evals/run_evals.py` | present |
| ci_config | `.github/workflows/` | present; no retrieval-quality gate on builds |

## 11. Components missing or stubbed (each verified by search or reading code)

1. **BM25**: keyword search is Postgres `ts_rank_cd` over an OR-joined tsquery (`services/search.py:95-97`); no BM25 scoring, no separate inverted index.
2. **Metadata pre-filtering on /ask**: the request has no source, language or date filter except `as_of` (`schemas.py` `AskRequest`); the only filters (`services/search.py` `_current`: not-a-duplicate, ingested by `as_of`) are in the same SQL as the HNSW ordering. Whether pgvector applies them before or after the approximate scan is **unverified** here.
3. **Cross-encoder reranker**: implemented, `ATLAS_RERANK=off`; its A/B (commit `bde79bb`, whose message says "it times out on every query") did not clear the 150 ms timeout (`ATLAS_RERANK_TIMEOUT_MS`).
4. **Weighted final score**: implemented, off (lowered top-1 hits in the eval); shadow-logged.
5. **Parent-document retrieval, contextual compression, query decomposition for multi-hop**: no code. (The planner emits up to 4 variants; the research agent does multi-step reading; neither decomposes.)
6. **Live tools registry (price, fx, weather, sports, package versions)**: absent. Read-only external MCP tools exist (`assistant/mcp_client.py`) when `ATLAS_MCP_SERVERS` is set.
7. **News ingestion**: absent. Today's facts come from live web search per question (`assistant/web.py`), not an ingested, deduped, freshness-tagged corpus.
8. **Split A/B serving**: not on main (`app/retrieval/` has no `splitab.py`); exists only on an unpushed branch.
9. **Durable log sink**: not on main; per-query logs are process stdout; the answer log is ephemeral with a 6-hour export.
10. **Retrieval-quality gate on builds**: CI runs unit tests only; the golden-set eval needs a running server with models and is not a build gate.
11. **Embedding model**: all-MiniLM-L6-v2 (384 dims, 256-token limit, English), chosen to fit 512 MB; passages over its limit are truncated (`worker/embed.py:15`, `documents.py:22`).
12. **Per-stage budgets**: defined and observed (`retrieval/budget.py`), enforced only for stages named in `BUDGET_ENFORCE` (default: none); the planner and judge have hard timeouts (`search.py:303`, `:420`).
13. **Auth/rate limits**: admin token + optional TOTP (`admin.py`), API keys, in-memory per-process rate limiter (`ratelimit.py:14`); not shared across processes.

## 12. Open questions for Phase 1 and 2

* Does the live index match the embedding model, and does vector search score known phrases above 0.3? (Measured earlier: yes, for the three original sources; re-measured in Phase 1.)
* Do the ~150 database-backed tests pass in CI on this commit? (CI green at `b5af76a`.)
* Does any ingest path skip validation of empty or too-short text? (Phase 2A.)
