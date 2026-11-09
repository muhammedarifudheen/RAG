# Golden set validation

`golden_set.jsonl` against `https://atlas-api-uxze.onrender.com`. **All checks passed.**

| Check | Result |
| --- | --- |
| 1. Every relevant_path exists in the knowledge base | PASS |
| 2. Every expected_state is valid | PASS |
| 3. Difficulty distribution matches the spec (20 / 10 / 5 / 5) | PASS |
| 4. No near-duplicate questions (cosine over 0.95) | PASS |
| 5. Vector-only baseline leaves headroom (mean nDCG@10 under 0.85) | PASS |

## 1. Every relevant_path exists in the knowledge base: PASS

- 17 files found in the knowledge base
- 62 path references checked

## 2. Every expected_state is valid: PASS

- states: ABSENT 12, CONFLICTED 0, INFERRED 4, KNOWN 11, PARTIAL 10, REFUSED 3

## 3. Difficulty distribution matches the spec (20 / 10 / 5 / 5): PASS

- failure: 20 (spec 20)
- multi-hop: 10 (spec 10)
- code-trace: 5 (spec 5)
- adversarial: 5 (spec 5)
- 40 entries in all

## 4. No near-duplicate questions (cosine over 0.95): PASS

- 780 pairs compared; the closest: F-A03/M-10 0.686, M-01/M-03 0.675, F-P07/M-04 0.634

## 5. Vector-only baseline leaves headroom (mean nDCG@10 under 0.85): PASS

- 25 questions with a retrieval target; mean nDCG@10 = 0.397

## nDCG@10 by question (vector-only)

| Id | nDCG@10 |
| --- | --- |
| F-P04 | 0.000 |
| F-P08 | 0.000 |
| F-P12 | 0.000 |
| M-10 | 0.000 |
| T-01 | 0.000 |
| F-P02 | 0.235 |
| M-01 | 0.237 |
| F-P10 | 0.264 |
| F-P05 | 0.307 |
| M-07 | 0.307 |
| T-02 | 0.345 |
| T-06 | 0.384 |
| F-P06 | 0.387 |
| M-08 | 0.390 |
| M-12 | 0.437 |
| T-04 | 0.469 |
| M-11 | 0.580 |
| M-04 | 0.591 |
| F-P03 | 0.613 |
| M-03 | 0.613 |
| T-05 | 0.613 |
| F-P11 | 0.631 |
| F-P07 | 0.693 |
| M-02 | 0.832 |
| M-06 | 1.000 |
