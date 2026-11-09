# Weighted ranking vs production order: 3 interleaved rounds on `/ask`

40 golden questions, 3 rounds, both arms asked back to back per question (order alternating).
Raw rows and per-round numbers: `ab_repeat.json`. Retrieval metrics cover the 25 questions with a
retrieval target; citation figures the 21 with citations in both arms.

## Paired difference (weighted minus production)

| Metric | Production | Weighted | Mean diff | 95% interval | Better / tied / worse | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| recall@5 | 0.382 | 0.379 | +0.006 | -0.016 to +0.028 | 3 / 20 / 2 | within noise |
| nDCG@10 | 0.387 | 0.383 | +0.002 | -0.012 to +0.021 | 2 / 21 / 2 | within noise |
| MRR | 0.547 | 0.538 | -0.002 | -0.027 to +0.020 | 1 / 23 / 1 | within noise |
| hit@1 | 0.507 | 0.500 | 0.000 | -0.040 to +0.040 | 1 / 23 / 1 | within noise |
| citation precision | 0.418 | 0.394 | -0.033 | -0.110 to +0.037 | 4 / 11 / 6 | within noise |

## Other measures (means over rounds)

| | Production | Weighted |
| --- | --- | --- |
| correct-refusal rate | 0.929 | 0.881 (one round 0.786) |
| false-refusal rate | 0.213 | 0.243 |
| degraded rate | 0% | 0% |
| first token p50 / p95 | 27 s / 89 s | 27 s / 79 s |

## Conclusion

The earlier gap (nDCG@10 0.389 vs 0.353, citation precision 0.505 vs 0.433) was noise: with
repeats the two arms are indistinguishable, and 20 of 25 questions rank identically. Production
itself moved between rounds by as much as the earlier gap (citation precision 0.485 to 0.368).
Weighted ranking stays off. No ranking change helps here, which matches the earlier finding that
retrieval recall, not ordering, is the limit. Latency is dominated by the free language models.
