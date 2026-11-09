# Golden set: 40 hard questions

`golden_set.jsonl`, for the public server's starter sources (pallets/itsdangerous, the Python `hmac`
docs, HMAC on Wikipedia). One JSON object per line:

| Field | Meaning |
| --- | --- |
| `id`, `category` | `F-P`/`F-A` failure modes, `M` multi-hop, `T` code trace, `V` adversarial |
| `question` | what is asked |
| `relevant_paths` | file paths, optionally `{"file", "lines": [start, end]}`; suffix-matched; never chunk ids |
| `expected_state` | KNOWN, INFERRED, PARTIAL, ABSENT, CONFLICTED or REFUSED |
| `rationale` | one line on why the question is hard |
| `origin` | `constructed`: written against the corpus, **not** taken from the query log |
| `vector_check` | what vector-only `/search` returned when the set was built: rank-1 chunk, its score, the margin over rank 2, and the rank of the first relevant chunk |

## Where the questions came from

The Insights query log needs the admin password and a one-time code, and the free server wipes it
on every restart, so it holds almost nothing but evaluation runs. The 20 failure-mode questions
are therefore **constructed**, not logged: PARTIAL ones where the sources cover part of the
question, ABSENT ones that sit in the domain but are not covered. Expected states are read from
the sources by hand, not classified by a model. When a real export of the Insights "gaps" list is
available, replace the `F-*` entries with the real PARTIAL and ABSENT queries.

## Headroom rule

A candidate was to be rejected if vector-only search already returned a relevant chunk at rank 1
with a score margin over 0.15. None of the 47 candidates met that: on this small corpus the top
scores are bunched (the largest rank-1 margin seen was 0.104), so the rule filtered nothing. The
40 were chosen instead by how hard retrieval found them (deepest rank of the first relevant
chunk, then smallest margin); the seven left out were the easiest. ABSENT and REFUSED entries
have no retrieval target, so the rule does not apply to them: their headroom is whether the
answer declines, not what ranks first.

## Distribution

| Category | Entries | KNOWN | INFERRED | PARTIAL | ABSENT | REFUSED |
| --- | --- | --- | --- | --- | --- | --- |
| fail-partial | 10 | 0 | 0 | 10 | 0 | 0 |
| fail-absent | 10 | 0 | 0 | 0 | 10 | 0 |
| multi-hop | 10 | 6 | 4 | 0 | 0 | 0 |
| code-trace | 5 | 5 | 0 | 0 | 0 | 0 |
| adversarial | 5 | 0 | 0 | 0 | 2 | 3 |
| **total** | **40** | **11** | **4** | **10** | **12** | **3** |

How hard retrieval found them (vector-only, top 10):

| Vector-only result | fail-partial | fail-absent | multi-hop | code-trace | adversarial | total |
| --- | --- | --- | --- | --- | --- | --- |
| miss (nothing relevant in top 10) | 3 | 0 | 1 | 1 | 0 | 5 |
| buried (relevant at rank 4-10) | 1 | 0 | 1 | 1 | 0 | 3 |
| buried (relevant at rank 2-3) | 5 | 0 | 4 | 1 | 0 | 10 |
| contested (rank 1, margin <= 0.15) | 1 | 0 | 4 | 2 | 0 | 7 |
| no retrieval target | 0 | 10 | 0 | 0 | 5 | 15 |

not selected: F-P01, F-P09, F-A11, M-05, M-09, T-03, V-06

CONFLICTED is allowed by the schema but unused: the starter sources do not contradict each other.

Run it (after the A/B decision):

```sh
python -m evals.run_evals --mode search --golden evals/golden/golden_set.jsonl
python -m evals.run_evals --mode ask --golden evals/golden/golden_set.jsonl --delay 2
```
