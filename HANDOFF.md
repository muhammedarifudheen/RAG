# Atlas: handoff (state as of 2026-11-10)

Everything here is in the repo `muhammedarifudheen/RAG`. Check out the branch
`evals/shadow-weighted-and-reranker-b` (it is ahead of `main`) to get the latest work.

## Where things are

- **Web** (`apps/web`): Next.js 14 static export on GitHub Pages (`/RAG`), the black "Dragon Court"
  redesign. Live: https://muhammedarifudheen.github.io/RAG/chat/
- **API** (`apps/api`): FastAPI + Postgres/pgvector on Render free (512 MB):
  https://atlas-api-uxze.onrender.com
- **Retrieval engine** (`apps/api/app/retrieval/`, see its README): weighted score, stage budgets,
  caches, adaptive top-k, optional cross-encoder reranker (`ATLAS_RERANK`, off), health, hard
  timeout, per-query latency budget (observe mode; weekly report workflow).
- **Evals** (`apps/api/evals/`, see its README): 40-question golden set (`golden/golden_set.jsonl`),
  validator, A/B scripts, reports in `evals/reports/`.

## Decisions made (with evidence in `evals/reports/`)

| Question | Result | Setting |
| --- | --- | --- |
| Weighted final score | tied legacy over 3 interleaved rounds (`ab_repeat.md`); fails ship rule | `RETRIEVAL_WEIGHTED_RANK` off, shadow-logged (`shadow_score` log line) |
| Cross-encoder reranker | 15 s/query on CPU vs 150 ms budget; times out 100% (`ab_reranker_b.md`, `rerank_diagnosis.md`) | `ATLAS_RERANK` off |
| Bottleneck | mostly ranking (recall@20 0.84 chunk-level / 0.92 file-level, hit@1 0.28 candidate order) (`bottleneck.md`) | n/a |

## Open items

1. Open the PR for branch `evals/shadow-weighted-and-reranker-b` into `main` (needs `gh auth login`;
   `gh` was installed with `winget install --id GitHub.cli`).
2. Re-decide the weighted score about two weeks after the shadow logging is deployed (compare
   `shadow_chosen` to `chosen` in the logs; re-run the golden set).
3. Not yet checked: that BM25 and vector both run in production, RRF fusion, metadata filters,
   chunk spans (cases F-P04, F-P12, F-P08, M-10).
4. A faster reranker (smaller model or GPU) is the only route to the measured ranking gain.

## Setting up on another computer

```bash
git clone https://github.com/muhammedarifudheen/RAG.git atlas && cd atlas
git checkout evals/shadow-weighted-and-reranker-b
pnpm install                      # web (needs Node 20+)
cd apps/api && pip install -e ".[dev]"   # API (Python 3.11+)
```

- Local test runs without a database: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DATABASE_URL=sqlite://
  python -m pytest --noconftest tests/test_eval_metrics.py tests/test_retrieval_core.py`.
  DB-backed tests run in CI.
- Evals against the live server: `python -m evals.run_evals --api https://atlas-api-uxze.onrender.com
  --mode ask --golden evals/golden/golden_set.jsonl` (a 40-question `/ask` run takes 20-40 minutes).
- Dev server: `pnpm --filter web dev`. The old machine ran it through `.claude/launch.json`, which is
  local only.
- Keys and secrets live in Render and GitHub settings, not in the repo.

## Quirks of the old machine (may not apply)

Windows Application Control blocked torch/psycopg, so the reranker eval used ONNX Runtime; no
Docker or local Postgres. The reranker model (2.27 GB fp32) is downloaded from
`onnx-community/bge-reranker-v2-m3-ONNX` on first run.
