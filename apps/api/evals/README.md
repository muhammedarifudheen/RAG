# Evals

Measures how well Atlas finds and answers, so a change to chunking, embeddings, reranking
or prompts is judged by numbers, not by trying a few questions.

It talks to a running API over HTTP, standard library only, so the same command checks a
local API, staging or the public server.

## Run it

```sh
cd apps/api
python -m evals.run_evals --mode search            # vector search only: free, no model called
python -m evals.run_evals --mode ask --delay 2     # the whole pipeline (calls models)
```

Useful flags: `--api URL`, `--token T`, `-k 10` (excerpts retrieved), `--limit N`,
`--no-plan` / `--no-rerank` (ask mode: switch a stage off to see what it adds),
`--out report.json`.

Two question sets are included:

- `golden/atlas.jsonl`: questions about **this repository**; ingest it first (paste
  `https://github.com/muhammedarifudheen/RAG` on the Ingest page, or `POST /ingest`).
- `golden/live.jsonl`: questions about the public server's starter sources (itsdangerous and
  HMAC). Run it with `--golden evals/golden/live.jsonl --api <the server>`;
  `baseline-live-search.json` is its search-mode baseline. The free server sleeps when idle,
  so the first request can take a minute.

## What it reports

| Metric | Meaning |
| --- | --- |
| `hit@k` | A relevant file is in the top k excerpts |
| `recall@k` | The share of a question's relevant files found in the top k |
| `mrr` | 1 / the rank of the first relevant excerpt |
| `ndcg@k` | Ranking quality, rewarding relevant excerpts near the top |
| `answer_coverage` | Share of the required phrases (`must_include`) in the answer |
| `citation_precision` | Share of the answer's citations that are verified and point at a relevant file |
| `cited_rate`, `verified_citation_share` | Answers that cite at all; citations whose lines the model was shown |
| `false_refusal_rate` | Answerable questions Atlas declined (lower is better) |
| `correct_refusal_rate` | Unanswerable questions Atlas declined (higher is better) |
| `latency_p50_ms`, `latency_p95_ms` | Time per request, as the client saw it |

In `search` mode only the retrieval metrics and latency are reported. In `ask` mode, retrieval
is scored on the excerpts the model was given (after planning, fusion and reranking), not on
the raw search.

## Guarding against regressions

```sh
python -m evals.run_evals --mode search --out evals/baseline.json     # record a baseline
python -m evals.run_evals --mode search --baseline evals/baseline.json --max-drop 0.05
python -m evals.run_evals --mode search --min hit@5=0.7 --min mrr=0.5  # absolute floors
```

It exits 1 if any metric is more than `--max-drop` worse than the baseline (counts and
timings are not compared), or under a `--min` floor. Commit `baseline.json` once you trust
a run, and run this in CI against a staging server.

## The golden set

`golden/atlas.jsonl`, one JSON object per line (lines starting with `#` are skipped):

```json
{"id": "hybrid-search",
 "question": "How does hybrid search combine vector and keyword results?",
 "relevant": ["apps/api/app/services/search.py"],
 "must_include": ["reciprocal"]}
```

- `relevant`: files a good answer must come from. A path is matched as a suffix, so
  `search.py` also matches `apps/api/app/services/search.py`. For a particular passage use
  `{"file": "search.py", "lines": [120, 160]}`; an excerpt counts if its lines overlap.
- `must_include`: phrases the answer should contain (case-insensitive); a cheap check on
  substance. Leave it empty when no phrase is safe to require.
- `answerable: false`: the knowledge base cannot answer this; the right behaviour is to decline.

Make the set your own: take real questions from the Insights page (what people ask, what
fails), note the file that answers each, and add them. Thirty to fifty varied questions
(including a few unanswerable ones) is enough to see real changes; ten is a smoke test.

## Limits

- Relevance is judged by file (and optional lines), so it does not know that two different
  files can both answer a question; list every acceptable file in `relevant`.
- `must_include` is a string match, not a judge of meaning. A model-graded faithfulness score
  would be the next step.
- Ask-mode results vary run to run (the models are not deterministic); compare averages, and
  use a generous `--max-drop`.
