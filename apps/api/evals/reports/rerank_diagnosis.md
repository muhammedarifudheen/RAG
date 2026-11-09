# Why bge-reranker-v2-m3 takes seconds per query on a CPU

Measured on an i7-1355U laptop (2 performance + 8 efficiency cores, 12 threads), idle, with
the 800 real candidate chunks of the 40-question golden set (20 per question), the ONNX export
of the model, `max_length` 256, batch 8. No production config was changed.

**Bottleneck: raw compute, not a misconfiguration. 82% of the time is matrix multiplication in
a 24-layer, 1024-wide model, over about 4,900 padded tokens per query.** It runs at about
266 tokens/s, roughly 160 GFLOPS, on this CPU, which is 3.1 ms per token: 15 s for 4,948 tokens.
A second, smaller cause is chunking: whole documents and whole classes are being reranked.

| # | Check | Finding | Verdict |
| --- | --- | --- | --- |
| 1 | Provider | Available: CPU and Azure. **Granted: `CPUExecutionProvider` only.** Graph optimisation `ORT_ENABLE_ALL`, default threads. | Not falling back to anything slower. |
| 2 | Token lengths | Pair length (question + chunk): median 192, mean 291, p90 714, p99 1,567, max 1,579. **37% of pairs exceed 256** and are cut to it (37% sit exactly at 256 afterwards); 71% exceed 128. Of 800 candidates, 97 are over 600 tokens: whole documents (`hmac.html`, the Wikipedia HMAC page), whole classes and module-level chunks. Padding wastes **24.8%** of the tokens computed as ranked (13.4% if sorted by length). | Chunking is part of the cost: not every chunk hits 256, but over a third do, and the very long ones are whole files. |
| 3 | Batched? | **Yes**: 20 pairs make 3 model calls (shapes 8×256, 8×256, 4×256), not 20. But batching does not help on a CPU: whole-query time by batch size was 12.7 s (1), 14.6 s (4), 14.4 s (8), **23.4 s (20)**. | Batching is correct and irrelevant; very large batches hurt. |
| 4 | Precision | The weights are **fp32** (2.27 GB for 568M parameters is 4.0 bytes each). On this CPU: fp32 15.3 s, **int8 9.1 s (1.7× faster)**, **fp16 20.4 s (33% slower)**. | fp16 is slower on a CPU, as suspected. int8 is faster. |

Other measurements: tokenizing is **0.09%** of the time (12 ms of 15 s). Threads: 1 thread 43.7 s,
4 → 21.3 s, 6 → 17.7 s, 8 → 22.5 s, 10 and 12 → 16.5 s: it scales only 2.7× because 8 of the 12
threads are slower efficiency cores. The model's 250k-word embedding table accounts for 256M
of its 568M parameters but costs no compute, so the cost is that of about 310M parameters.

## A fix for each bottleneck (none applied)

Token counts per query come from the real candidates; times use the measured 3.1 ms per
token (fp32) and the measured int8 ratio of 0.45.

| Bottleneck | Fix | Tokens/query | fp32 | int8 |
| --- | --- | --- | --- | --- |
| Today | top 20, cap 256 | 4,948 | 15.4 s | 6.9 s |
| Padding (25%) | sort the pairs by length before batching | 4,298 | 13.4 s | 6.0 s |
| Whole-file chunks and truncation | rerank only section, function and class-sized chunks (skip whole-module chunks), and cap at 128 tokens | 2,523 (with sorting) | 7.9 s | 3.5 s |
| Too many candidates | rerank the top 10, not 20 | 2,408 at cap 256 | 7.5 s | 3.4 s |
| Together | top 10, cap 128, sorted | 1,279 | 4.0 s | 1.8 s |
| Together, batch of 1 | as above, no padding at all | 1,190 | 3.7 s | 1.7 s |
| Precision | int8 (not fp16) | | | ×0.45 |
| The model itself (82% MatMul) | a much smaller cross-encoder: the MiniLM-L6 class has about 27× fewer compute parameters, **an estimate that is not measured here** | 1,279 | | about 0.07 s |

**Reading it:** every cheap fix together still leaves about 1.7 s against a 150 ms budget, a
factor of 12. Only a smaller reranker (or a GPU with real throughput; the integrated one here
managed 10 s) can reach 150 ms. The reranker is worth having (it raised hit@1 from 0.28 to
0.44 on the hard set), so the next experiment is a small cross-encoder at top 10, capped at
128 tokens, on this golden set.
