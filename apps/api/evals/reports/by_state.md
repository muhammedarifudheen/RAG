# Diagnosis: is hit@1 0.507 a retrieval failure or a set-composition artifact?

The 25 retrieval-scored golden questions by state. "Search" is the candidate order `/search`
returns (top 20). "Ask" is the full `/ask` pipeline (production arm of the interleaved repeat,
mean of 3 rounds). "By chunk" is the metric as defined (a hit must overlap a target's line range);
"by file" counts any chunk of a target's file. Data: `by_state.json`, `evals/diagnose_by_state.py`.

| State | N | Paths / question | Search hit@1 (chunk / **file**) | Search nDCG@10 | Search recall@20 (chunk / file) | Ask hit@1 / nDCG@10 |
| --- | --- | --- | --- | --- | --- | --- |
| KNOWN | 11 | 3.09 | 0.45 / **1.00** | 0.52 | 1.00 / 1.00 | 0.70 / 0.51 |
| INFERRED | 4 | 2.50 | 0.25 / **0.50** | 0.41 | 0.75 / 0.75 | 0.75 / 0.61 |
| PARTIAL | 10 | 1.80 | 0.10 / **0.70** | 0.31 | 0.70 / 0.90 | 0.20 / 0.16 |
| All | 25 | 2.48 | 0.28 / **0.80** | 0.42 | 0.84 / 0.92 | 0.51 / 0.39 |

First relevant rank, by chunk and by file (1 / 2-5 / 6-10 / 11-20 / absent):

| State | By chunk | By file |
| --- | --- | --- |
| KNOWN | 5 / 5 / 0 / 1 / 0 | **11 / 0 / 0 / 0 / 0** |
| INFERRED | 1 / 2 / 0 / 0 / 1 | 2 / 1 / 0 / 0 / 1 |
| PARTIAL | 1 / 6 / 0 / 0 / 3 | 7 / 1 / 1 / 0 / 1 |
| All | 7 / 13 / 0 / 1 / 4 | 20 / 2 / 1 / 0 / 2 |

## The metric definitions

- **hit@1 is chunk-level and any-target.** It is 1 if the top-1 *chunk* is in a relevant file and,
  when the target pins lines, overlaps them. It counts any of a question's targets, not a specific
  one, so a question with 3 relevant paths is not penalised for having 3. Not a bug.
- **But the line ranges make it strict.** Most targets pin lines, so the right file with a
  different chunk is a miss. That is where the gap between the chunk and file columns comes from.
- **nDCG@10 is depressed by the number of paths.** Its ideal needs every target found (one per
  target), so a 3-path question scores at most 1.0 only if all 3 appear. KNOWN averages 3.1 paths:
  its nDCG@10 is 0.52 although the right file is first for all 11. A design choice, not a bug,
  but it makes the headline low on multi-path sets.

## Verdict

**Mostly a metric artifact of line-range labels; the bottleneck is chunk choice within the right
file, not retrieval or ranking.**

- By your literal rules: KNOWN chunk-level hit@1 is 0.45 (under 0.8, "real failure") and PARTIAL
  0.10 (under 0.4), and chunk recall@20 is 0.84 (under 0.85).
- But by file, KNOWN hit@1 is **1.00**, overall hit@1 is 0.80 and recall@20 is 0.92. Retrieval finds
  the right file for every easy question and ranks it first. What it often fails to put first is
  the specific chunk the labels name.
- PARTIAL is the weakest by either measure (hit@1 0.70 by file, 0.20 in `/ask`; 3 questions with
  no labelled chunk in the top 20, F-P04/F-P12 being wrong-chunk, F-P08 an absent file), as
  expected for questions whose answer is only partly in the corpus.
- **This revises what I said earlier.** My diagnosis called ranking the larger loss using chunk-level
  numbers (hit@1 0.28). By file the candidate order already puts the right file first 80% of the
  time, so the room for a reranker is much smaller than the chunk-level gap suggested, and the
  reranker's measured gain (hit@1 0.28 to 0.44) was also chunk-level. Report per-state, and both
  chunk and file numbers, from now on.

## Not done

The reranker arm was not run, as asked. Whether the labels' line ranges are the right standard
(versus accepting any chunk of the right file for answerability) is a decision for you; I have
not changed the golden set or the gating metric.
