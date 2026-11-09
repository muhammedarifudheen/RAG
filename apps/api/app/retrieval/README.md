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
