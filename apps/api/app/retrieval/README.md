# Retrieval core

How retrieved excerpts are ranked, budgeted, cached and measured. It wraps the existing
pipeline (query planner, hybrid search, relevance judge) in `routers/search.py`; it does not
replace it.

## What it does

| Piece | Where | Behaviour |
| --- | --- | --- |
| Final score | `scoring.py` | `0.45 rerank + 0.20 rank-fusion + 0.15 trust + 0.10 freshness + 0.10 source record`. Ties: newer source, higher trust, shorter excerpt, exact identifier match. Never similarity alone: unjudged excerpts use it only as their rerank signal. Per request: `weighted_rank`; the server default `RETRIEVAL_WEIGHTED_RANK` is **off**: on the public server's 12-question set it lowered hit@1 from 1.00 to 0.71 (legacy order vs weighted, 2-3 timeouts per run), so it stays opt-in until a larger set shows a gain. |
| Freshness | `scoring.py` | Exponential decay, half-life 30 days for code and 90 for documents. |
| Source record | `state.py` | From thumbs on answers that used the source (90 days, smoothed `(up+1)/(up+down+2)`); neutral 0.5 with no votes. |
| Stage budgets | `budget.py` | The planner (`RETRIEVAL_PLAN_BUDGET`, 6 s) and the judge (`RETRIEVAL_JUDGE_BUDGET`, 12 s) give way to a fallback instead of stalling; a failed vector search falls back to keywords (already so). Each sets `degraded` and a reason; the footer reads `[degraded: reason]` and the web app shows a chip. |
| Adaptive top-k | `topk.py` | 3 for a short fact, 5 to explain or synthesise, 8 to compare; never more than 8 unless the request sets `top_k`. |
| MMR | `services/search.py` | λ = 0.7. |
| Retrieval cache | `state.py` | Query + limit + `as_of` + knowledge-base version, one hour. |
| Knowledge-base version | `state.py` | A fingerprint of the sources (count, newest, versions, update times) plus a counter bumped on every ingest and removal. It is in the retrieval and answer cache keys, so no cache serves a stale knowledge base. |
| Embedding cache | `embedding.py` | Keyed by the sha256 of the lower-cased, space-collapsed text; least recently used, 512 entries. |
| Negative cache | `routers/search.py` | An `absent` answer is kept an hour, any other cached answer a day. |
| Logging | `routers/search.py` | One `retrieval {...}` line per question: query hash, rewritten queries, ids retrieved and chosen, final scores, seconds per stage, cache hits, degraded reasons. |

## What it does not do (and why)

- **Cross-encoder rerank.** The relevance judge (small models, one call per excerpt) is still
  the reranker. `bge-reranker-v2-m3` does not fit the free server's 512 MB; a small ONNX
  cross-encoder or a hosted reranker is the next step.
- **Separate BM25 index, Parquet/Lance metadata, sharding, HNSW warm-up.** Keyword search is
  Postgres full-text search; the metadata is in Postgres. These need a larger server.
- **Contextual compression, parent-document retrieval, self-query filters, speculative
  retrieval.** Not built.
- **Stage budgets in milliseconds.** The spec's budgets (40 ms to plan, 120 ms to rerank)
  assume local models. The planner and judge call remote free models, so their budgets are in
  seconds. Vector and keyword search have no time limit of their own beyond the database's.
- **Targets.** First-token latency under 900 ms is not reachable on the free server (answers
  take about 30 s). Quality targets are measured by `apps/api/evals`.

## Measuring a change

```sh
python -m evals.run_evals --mode ask --rank weighted --out weighted.json
python -m evals.run_evals --mode ask --rank legacy   --out legacy.json
```

Keep a change only if it moves a metric the right way (`hit@k`, `ndcg@k`, `mrr`,
`citation_precision`, `degraded_rate`); `RETRIEVAL_WEIGHTED_RANK=true` turns the weighted ranking on for every request.

## Cross-encoder reranker (`ATLAS_RERANK=on|off`, default off)

`reranker.py` reranks the top 20 candidates of hybrid retrieval with `bge-reranker-v2-m3`,
attaches each excerpt's `rerank_score` (the raw logit; in the response, the log line and the
answer log) and keeps the top 5. It replaces the model-by-model relevance judge while on.

- **Loaded once**, in the background at startup, only when on. Until it has loaded, or if
  loading fails, `/ask` uses the RRF order and the answer is `degraded` with the reason.
- **Timeout:** `ATLAS_RERANK_TIMEOUT_MS`, default 150 (the spec's, meant for a GPU). Over it,
  the RRF order and `degraded`. On a CPU, 20 pairs take seconds, so at 150 ms it degrades on
  every answer; raise it to see the reranker's effect.
- **Runtime:** ONNX Runtime on the community export of the same weights
  (`ATLAS_RERANK_ONNX_REPO`, `ATLAS_RERANK_PRECISION=fp32|int8`), not sentence-transformers:
  torch is not in the server image.
- **Memory:** about 2.3 GB (fp32) or 570 MB (int8). The free 512 MB server cannot hold either,
  and an out-of-memory kill is not an exception a fallback can catch. Turn it on only
  where the memory exists.

### The production path, in detail

- **Hard timeout.** The wall-clock budget (`ATLAS_RERANK_TIMEOUT_MS`, 150) is enforced two ways:
  the caller stops waiting at the budget, and the abandoned work stops at its next batch
  boundary instead of finishing in the background. 20 candidates go in batches of 8, so a
  batch that has started still runs to its end (a model call cannot be interrupted); at most
  one batch of overrun, never all three.
- **One at a time.** While an overrun is still finishing, the next query skips the reranker
  (`rerank_busy`) rather than stacking a second one on the CPU.
- **On a timeout, error or busy model:** the RRF order, `degraded: true`,
  `degraded_reason: "rerank_timeout"` and the `[degraded: …]` chip. A model that is not loaded
  gives `degraded_reason: "rerank_unavailable"` instead.
- **Log line per query** (`retrieval {...}`): `rerank_ms`, `rerank_batches`,
  `rerank_timed_out`, `rerank_scores` of the returned chunks, `degraded_reason`.
- **The answer stream.** The excerpts must be chosen before the answer is written, so
  reranking cannot run beside it. It cannot hold it up for long either: the budget caps the wait
  at 150 ms, then generation and streaming start, from the reranked order or the RRF order.
- **Start-up and health:** the model loads and warms up in the background at boot,
  `/health/reranker` reports it, and slow reranking switches the flag off (see above).

## Per-query latency budget (`BUDGET_*`)

Every query's stages are timed against a budget, in milliseconds (the spec's, overridable):

| Stage | Budget | What is timed |
| --- | --- | --- |
| `rewrite` | 40 | the query planner |
| `embed` | 60 | embedding the query (per search) |
| `bm25` | 30 | full-text keyword search (per search) |
| `vector` | 80 | the vector (pgvector) search (per search) |
| `fuse` | 5 | rank fusion, MMR and the newer-source tie-break |
| `rerank` | 150 | the relevance judge, or the cross-encoder when `ATLAS_RERANK=on` |
| `assemble` | 20 | building the prompt: instructions, excerpts, history |
| `first_token` | 600 | from the request to the first streamed word |
| `full_answer` | 3000 | from the request to the finished answer |

A stage that runs more than once (each planned search embeds and searches) is summed for
`stage_ms`, and breaches when a single run is over.

- **Observe, by default** (`BUDGET_ENFORCE` empty): nothing changes. Each answer carries
  `stage_ms` and `budget_breached` (the first stage over its budget), the `retrieval {...}` and
  `answer {...}` log lines carry them, and the answer log keeps them (`answer_log.stats`).
- **Enforce** (`BUDGET_ENFORCE=all`, or stages such as `rewrite,rerank`): when an enforced stage
  breaches, the optional stages that remain (the planned searches after the first, and the
  reranker or judge) are skipped, the planner and judge get only their budget as a timeout, the
  answer is `degraded: true` with `degraded_reason: "budget_<stage>"` and the chip
  `latency budget: <stage> over N ms`, and it is still answered (RRF order, top excerpts).
  `first_token` and `full_answer` cannot skip anything, since they happen last; enforcing them
  only marks the answer.
- **Weekly report:** `GET /analytics?metric=budget&window=7` (admin): the share of answers
  degraded or over a budget, and per stage how often it breached, how often first, and its
  median and 95th percentile. The *Weekly latency report* workflow writes it to the Actions
  summary every Monday.

The defaults describe a fast local stack. The public server's planner takes about 1 s, its
search about 5 s, its relevance judge about 8 s and a whole answer 16-19 s, so every stage
breaches there: that is why it starts in observe mode. Read the weekly report, then enforce
stage by stage, starting with the optional ones (`rewrite`, `rerank`).
