# Three-arm A/B on the 40-question golden set

Run serially on an idle laptop against the public server. Raw results: `ab_arms.json` (retrieval
arms), `ab_ask_legacy.json` and `ab_ask_weighted.json` (answers).

## How the arms were measured

| Arm | Definition | Retrieval metrics | Answer metrics |
| --- | --- | --- | --- |
| **A** | vector-only | the order `/search` returns | `/ask` with the weighted ranking off (the production order) |
| **B** | vector, then reranker, 150 ms timeout, RRF fallback | the real reranker, run here (the free server cannot host it) | the same as A: on this CPU all 40 queries time out and fall back |
| **C** | vector, reranker, then the weighted final score | the same scores, then the weighted score with the reranker as its rerank signal | `/ask` with the weighted ranking on: the nearest measurable thing, since under the 150 ms fallback C is the weighted score without a reranker |

Retrieval metrics are over the whole top-20 each arm orders, on the 25 questions with a retrieval
target. Answer metrics are over all 40 (V-01, a prompt injection, was refused with HTTP 400 in
both runs: counted as a correct refusal).

## Results

| Metric | A | B | C |
| --- | --- | --- | --- |
| recall@5 (retrieval) | 0.446 | 0.446 | 0.439 |
| nDCG@10 (retrieval) | 0.419 | 0.419 | 0.405 |
| MRR (retrieval) | 0.485 | 0.485 | 0.470 |
| hit@1 (retrieval) | 0.280 | 0.280 | 0.280 |
| total p50 / p95, retrieval only | 1.4 s / 2.3 s | 1.6 s / 2.5 s | 1.6 s / 2.5 s |
| degraded rate (reranker over 150 ms) | 0% | **100%** | **100%** |
| recall@5 (`/ask`) | 0.340 | 0.340 | 0.374 |
| nDCG@10 (`/ask`) | 0.353 | 0.353 | 0.389 |
| MRR (`/ask`) | 0.520 | 0.520 | 0.560 |
| hit@1 (`/ask`) | 0.480 | 0.480 | 0.560 |
| citation precision (`/ask`) | 0.433 | 0.433 | 0.505 |
| correct-refusal rate (ABSENT + REFUSED, 15) | 12/15 = 0.80 | 0.80 | 0.80 |
| total p50 / p95, whole answer | 16.5 s / 91.0 s | same | 14.9 s / 45.1 s |
| first token p50 / p95 | 15.0 s / 83.6 s | same | 14.1 s / 42.1 s |

If the reranker were fast (no timeout), retrieval would be: B nDCG@10 0.486, MRR 0.558, hit@1
0.44; C nDCG@10 0.469, MRR 0.553, hit@1 0.44, at 16.4 s p50 and 18.1 s p95 for the search plus
the reranker.

## Ship decision (all four must hold)

| Criterion | B | C |
| --- | --- | --- |
| Beats A on nDCG@10 and MRR | no (equal: every query falls back) | no (retrieval: worse) |
| p95 first token under 900 ms | no | no (and neither is A: 83.6 s) |
| Degraded rate at most 1% | **no: 100%** | **no: 100%** |
| Correct-refusal rate not lower than A | yes (equal) | yes (equal) |

**Ship nothing.** B and C fail on degraded rate outright, and nothing, A included, can meet a
900 ms first token with a 15 s language-model call in the path.

## What the data says

- **Ranking is not the whole story, and it is not nothing.** A fast reranker would lift
  retrieval hit@1 from 0.28 to 0.44. But the right file is in the top 20 for only 84% of
  questions and 60.5% of relevant targets are retrieved there at all, so retrieval recall caps
  what any reranker can do (recall@5 stayed at 0.445 even with no timeout).
- **The reranker is a latency problem.** 15 s median on this CPU against a 150 ms budget (see
  `rerank_diagnosis.md`).
- **A lead worth following:** in the full `/ask` pipeline the weighted ranking (no reranker)
  scored higher than the production order on every retrieval and citation metric (nDCG@10
  0.389 against 0.353, MRR 0.560 against 0.520, citation precision 0.505 against 0.433) with
  identical refusals and no degradation. On the earlier 12 easy questions it was worse. These
  are single runs of a nondeterministic system on 25 scored questions, so the gap is within
  noise. It would need repeated runs before the setting changes; it stays off.
- **Latency:** the live server's p95 first token was 84 s (legacy) and 42 s (weighted): the free
  models, not retrieval, dominate it.
