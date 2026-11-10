# Diagnosis: is the bottleneck retrieval or ranking?

Source: `/search` top-20 (the candidate pool, before any reranking) for the 25 retrieval-scored
golden questions. Per-question data: `bottleneck.json` (`evals/diagnose_bottleneck.py`).

| | Result |
| --- | --- |
| questions where a relevant chunk is in the top 20 (recall@20 = 1) | 21 / 25 = **84%** |
| of those, the top-1 is correct | 7 / 21 = **33%** |
| questions never found in the top 20 (recall@20 = 0) | 4 / 25 = **16%** (F-P04, F-P08, F-P12, M-10) |
| first relevant chunk at rank 1 / 2-5 / 6-10 / 11-20 | 7 / 13 / 0 / 1 |
| hit@1 overall, candidate order | 0.28 (the full `/ask` pipeline reaches 0.51 after the planner and judge reorder) |

## Verdict

Both, but the larger loss is ranking.

- **By your rule, strictly:** recall@20 is 0.84, under 0.85, so this is a retrieval bottleneck, by
  one question (21/25 against 22/25 needed).
- **That 0.84 is partly my labels.** The golden targets are line ranges, so a chunk from the
  right file but another span counts as a miss. For F-P04 (`url_safe.py`) and F-P12 (`signer.py`,
  `timed.py`) the right file is in the top 20 with a different chunk. Counted by file, recall@20
  is 23/25 = **92%**, above the 0.85 line, and with hit@1 at 0.28 (under 0.7) the rule then says
  ranking.
- **Where the points go:** a perfect ranking of what was retrieved would reach hit@1 0.84, so
  ranking costs 0.56 (0.28 to 0.84) and retrieval 0.16 (0.84 to 1.0). Thirteen of 21 found
  questions have the answer at rank 2-5, one place short of the top, which is the shape a better
  ranker fixes.
- **Retrieval misses are two kinds.** F-P08 (JWS) and M-10 (is the payload encrypted) find nothing
  from the target file: conceptual questions whose answer is in a docstring or a Wikipedia page
  the query does not echo. F-P04 and F-P12 are chunk-span misses (above).

## What this changes

- A weighted score does not fix ranking (tied with legacy on 3 interleaved rounds), and the
  cross-encoder that does (hit@1 0.28 to 0.44 untimed) costs 15 s per query on this CPU. So the
  ranking gain is real and currently unreachable; it needs faster hardware or a smaller reranker.
- Retrieval fixes would lift at most 0.16 of hit@1 and cannot be tested from this data.

## Not checked

I did not verify that BM25 and vector search both run in production, that RRF fuses them, that no
metadata filter is dropping candidates, or how chunks split the relevant spans. Those are the next
checks if the retrieval side is pursued; the four missed questions (and F-P04, F-P12 for chunking)
are the cases to trace.
