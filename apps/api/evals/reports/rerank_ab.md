# Reranker A/B: bge-reranker-v2-m3 on the 40-question golden set

Search mode against the public server, `max_length` 256, batch size 8, 5 warm-up queries, run one question at a time on an otherwise idle laptop (i7-1355U, 12 logical cores), `--fallback-on-timeout 150ms`. The reranker reads the top 20 candidates of vector search. Raw per-question results: `rerank_ab_*.json`.

## Aggregate

| Metric | CPU fp32 | CPU int8 | GPU (Intel UHD, DirectML) fp32 |
| --- | --- | --- | --- |
| reranker mean ms | 17,872 | 7,677 | 10,104 |
| reranker median ms | 16,068 | 6,784 | 10,030 |
| reranker p50 ms | 16,068 | 6,784 | 10,030 |
| reranker p95 ms | 24,761 | 13,054 | 12,260 |
| reranker p99 ms | 25,469 | 13,621 | 14,908 |
| total (search + rerank) p50 ms | 18,184 | 7,620 | 10,586 |
| total p95 ms | 26,128 | 13,578 | 13,108 |
| total p99 ms | 26,631 | 14,864 | 15,637 |
| queries over the 150 ms budget | 100% | 100% | 100% |
| fallback fired (degraded) | 100% | 100% | 100% |

## Ranking quality (same candidates in every run)

| Metric | Vector order | Reranked (no timeout) | With the 150 ms fallback |
| --- | --- | --- | --- |
| hit@1 (CPU fp32) | 0.280 | 0.440 | 0.280 |
| hit@1 (CPU int8) | 0.280 | 0.440 | 0.280 |
| hit@1 (GPU (Intel UHD, DirectML) fp32) | 0.280 | 0.440 | 0.280 |
| MRR (CPU fp32) | 0.485 | 0.558 | 0.485 |
| MRR (CPU int8) | 0.485 | 0.566 | 0.485 |
| MRR (GPU (Intel UHD, DirectML) fp32) | 0.485 | 0.558 | 0.485 |
| nDCG@10 (CPU fp32) | 0.419 | 0.486 | 0.419 |
| nDCG@10 (CPU int8) | 0.419 | 0.487 | 0.419 |
| nDCG@10 (GPU (Intel UHD, DirectML) fp32) | 0.419 | 0.486 | 0.419 |
| recall@5 (CPU fp32) | 0.446 | 0.445 | 0.446 |
| recall@5 (CPU int8) | 0.446 | 0.445 | 0.446 |
| recall@5 (GPU (Intel UHD, DirectML) fp32) | 0.446 | 0.445 | 0.446 |

## Per question: reranker_ms / total_ms / timed_out

`timed_out` is true when the reranker took longer than 150 ms; `total_ms` is the search request plus the reranker.

| Question | CPU fp32 | CPU int8 | GPU (Intel UHD, DirectML) fp32 |
| --- | --- | --- | --- |
| F-P02 | 24,237 / 25,472 / true | 6,736 / 7,374 / true | 7,579 / 7,994 / true |
| F-P03 | 23,345 / 24,941 / true | 6,706 / 7,033 / true | 7,869 / 8,180 / true |
| F-P04 | 18,427 / 19,923 / true | 6,439 / 6,728 / true | 8,241 / 9,105 / true |
| F-P05 | 15,917 / 17,022 / true | 6,184 / 6,722 / true | 9,831 / 10,199 / true |
| F-P06 | 20,306 / 21,746 / true | 6,418 / 6,736 / true | 10,802 / 11,133 / true |
| F-P07 | 21,678 / 23,549 / true | 6,399 / 7,022 / true | 9,869 / 10,216 / true |
| F-P08 | 15,906 / 17,122 / true | 5,313 / 6,125 / true | 8,754 / 10,542 / true |
| F-P10 | 16,093 / 18,358 / true | 6,444 / 7,019 / true | 8,202 / 8,515 / true |
| F-P11 | 14,816 / 15,820 / true | 5,747 / 7,085 / true | 8,645 / 9,947 / true |
| F-P12 | 17,415 / 18,510 / true | 6,375 / 6,683 / true | 8,232 / 8,832 / true |
| F-A01 | 16,906 / 18,009 / true | 6,398 / 7,245 / true | 8,274 / 8,885 / true |
| F-A02 | 23,018 / 24,421 / true | 6,344 / 6,960 / true | 8,924 / 9,804 / true |
| F-A03 | 25,549 / 26,453 / true | 6,458 / 7,081 / true | 8,932 / 9,536 / true |
| F-A04 | 24,730 / 25,931 / true | 6,876 / 7,906 / true | 8,160 / 9,453 / true |
| F-A05 | 24,101 / 26,111 / true | 7,463 / 8,698 / true | 8,543 / 8,880 / true |
| F-A06 | 19,586 / 21,364 / true | 9,445 / 9,774 / true | 9,186 / 9,488 / true |
| F-A07 | 24,026 / 25,123 / true | 7,008 / 7,856 / true | 8,308 / 8,646 / true |
| F-A08 | 25,343 / 26,745 / true | 6,831 / 7,450 / true | 9,952 / 10,269 / true |
| F-A09 | 13,948 / 15,751 / true | 6,604 / 8,313 / true | 9,336 / 9,642 / true |
| F-A10 | 15,280 / 16,476 / true | 6,523 / 7,172 / true | 10,200 / 10,508 / true |
| M-01 | 17,531 / 18,728 / true | 6,160 / 9,629 / true | 10,000 / 10,629 / true |
| M-02 | 15,773 / 17,278 / true | 6,274 / 6,894 / true | 10,061 / 10,735 / true |
| M-03 | 16,609 / 19,006 / true | 8,894 / 9,210 / true | 10,106 / 10,757 / true |
| M-04 | 16,044 / 16,546 / true | 13,263 / 13,562 / true | 9,735 / 10,367 / true |
| M-06 | 15,616 / 16,823 / true | 11,307 / 11,612 / true | 10,321 / 10,643 / true |
| M-07 | 15,470 / 16,360 / true | 13,850 / 15,492 / true | 11,319 / 11,635 / true |
| M-08 | 15,101 / 16,899 / true | 10,295 / 10,606 / true | 10,227 / 11,067 / true |
| M-10 | 12,741 / 13,641 / true | 13,043 / 13,883 / true | 11,034 / 12,624 / true |
| M-11 | 14,607 / 15,411 / true | 6,525 / 7,727 / true | 11,174 / 11,511 / true |
| M-12 | 15,176 / 16,080 / true | 11,160 / 11,836 / true | 10,702 / 11,300 / true |
| T-01 | 12,717 / 14,511 / true | 6,339 / 6,852 / true | 11,781 / 12,342 / true |
| T-02 | 14,680 / 15,901 / true | 8,189 / 9,513 / true | 11,937 / 12,279 / true |
| T-04 | 15,156 / 16,536 / true | 8,779 / 9,104 / true | 11,435 / 11,737 / true |
| T-05 | 15,081 / 17,091 / true | 7,808 / 9,664 / true | 10,869 / 11,173 / true |
| T-06 | 15,412 / 16,517 / true | 7,304 / 7,601 / true | 12,188 / 12,977 / true |
| V-01 | 18,206 / 19,391 / true | 6,935 / 7,474 / true | 13,630 / 14,541 / true |
| V-02 | 16,032 / 18,433 / true | 7,216 / 7,802 / true | 15,725 / 16,338 / true |
| V-03 | 20,851 / 21,650 / true | 7,229 / 7,553 / true | 11,469 / 12,771 / true |
| V-04 | 17,315 / 18,822 / true | 7,441 / 7,771 / true | 12,174 / 13,033 / true |
| V-05 | 14,133 / 15,730 / true | 6,350 / 7,640 / true | 10,450 / 11,373 / true |
