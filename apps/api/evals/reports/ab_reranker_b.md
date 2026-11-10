# Arm B (reranker) on the 40-question golden set, three serial rounds

fp32 bge-reranker-v2-m3 on this CPU, max_length 256, batch 8, 5 warm-up queries, hard timeout
150 ms with RRF fallback. Same 25 questions scored on retrieval. Raw: `ab_arms_round{1,2,3}.json`.
The ranking is deterministic, so the rounds differ only in timing.

| | A (vector order) | B (reranker, 150 ms) | B with no timeout |
| --- | --- | --- | --- |
| hit@1 | 0.280 | 0.280 | 0.440 |
| nDCG@10 | 0.419 | 0.419 | 0.486 |
| MRR | 0.485 | 0.485 | 0.558 |
| recall@5 | 0.446 | 0.446 | 0.445 |
| timed out | n/a | 40/40 in every round (100%) | n/a |
| degraded rate | 0% | 100% | n/a |

Reranker time per query, p50 / p95: round 1 15.1 s / 16.0 s; round 2 15.3 s / 16.5 s; round 3
41.6 s / 104 s (the machine was busy in round 3). Against a 150 ms timeout, every query falls
back, so B served the vector order in all 120 queries and ties A exactly. Search plus capped
reranking: p50 0.7-1.3 s, p95 1.7-4.9 s, but only because the reranker is cut off at 150 ms.

## Decision

Ship rule: nDCG@10 and MRR beat legacy, p95 under 900 ms, degraded at most 1%. **Not met:** B
ties A on every metric and is degraded 100% of the time. Keep `ATLAS_RERANK` off; do not
enable it on this hardware.

The untimed column is the evidence worth keeping: with unlimited time the reranker lifts hit@1
from 0.28 to 0.44, nDCG@10 from 0.419 to 0.486 and MRR from 0.485 to 0.558 (recall@5 unchanged).
That gain only exists at 15 s a query; it is not shippable at a 150 ms budget on CPU. It would
need hardware or a much smaller model, which is a separate decision.
