"""A three-arm retrieval A/B on a golden set, run serially so the reranker is timed alone.

    A  vector-only: the order /search returns.
    B  vector, then the cross-encoder reranker under a hard timeout (default 150 ms): a query
       whose reranking overruns keeps the vector (RRF) order and counts as degraded.
    C  vector, reranker, then the weighted final score (rerank 0.45, rank fusion 0.20, trust
       0.15, freshness 0.10, source record 0.10), as production orders them. Under a timeout
       it is the weighted score of the vector candidates alone.

The reranker runs here, not on the server (the free server cannot hold it), so its time is this
machine's. Each query is reranked once; B and C are derived from the same scores, and the
no-timeout versions (`B_nt`, `C_nt`) show what each arm would give if the reranker were fast.

    python -m evals.ab_arms --api https://atlas-api-uxze.onrender.com \\
        --golden evals/golden/golden_set.jsonl --out evals/reports/ab_arms.json

Metrics use the whole top-20 each arm orders (not cut to 5), over the questions that have a
retrieval target. Total latency is the search request plus the reranker, capped at the timeout
for B and C (a hard timeout stops waiting there). The source record is neutral: there is no
feedback log to read it from.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.retrieval import scoring
from app.schemas import CodeChunk
from evals.metrics import Hit, Target, mean, percentile, score_retrieval
from evals.rerank import make_reranker, passage
from evals.run_evals import WARMUP_QUESTIONS, load_golden

HERE = Path(__file__).resolve().parent
KS = (1, 5, 10, 20)


def search(api: str, question: str, limit: int) -> tuple[list[CodeChunk], float]:
    query = urllib.parse.urlencode({"q": question, "limit": limit})
    started = time.perf_counter()
    with urllib.request.urlopen(f"{api.rstrip('/')}/search?{query}", timeout=120) as response:
        results = json.loads(response.read())["results"]
    return [CodeChunk(**r) for r in results], (time.perf_counter() - started) * 1000


def hits_of(chunks: list[CodeChunk]) -> list[Hit]:
    return [Hit(c.file, c.start_line, c.end_line) for c in chunks]


def reorder(chunks: list[CodeChunk], scores: list[float]) -> list[CodeChunk]:
    order = sorted(range(len(chunks)), key=lambda i: (-scores[i], i))
    return [chunks[i].model_copy(update={"rerank_score": round(scores[i], 4)}) for i in order]


def weighted(chunks: list[CodeChunk], query: str, vector_order: list[CodeChunk]) -> list[CodeChunk]:
    ranked = scoring.rank(chunks, query, candidates=vector_order, hit_rates={})
    return [c for c, _ in ranked]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--golden", type=Path, default=HERE / "golden" / "golden_set.jsonl")
    p.add_argument("--top", type=int, default=20, help="candidates the reranker reads")
    p.add_argument("--timeout-ms", type=float, default=150.0)
    p.add_argument("--backend", default="onnx", help="onnx (fp32), onnx-int8, onnx-dml, ...")
    p.add_argument("--max-length", type=int, default=256)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--warmup", type=int, default=5)
    p.add_argument("--out", type=Path, default=HERE / "reports" / "ab_arms.json")
    args = p.parse_args(argv)

    items = load_golden(args.golden)
    print(f"Fetching the top {args.top} for {len(items)} questions ...", flush=True)
    fetched = []
    for item in items:
        chunks, ms = search(args.api, item["question"], args.top)
        fetched.append((item, chunks, ms))

    print(f"Loading the reranker ({args.backend}) ...", flush=True)
    model = make_reranker("BAAI/bge-reranker-v2-m3", args.max_length, args.backend, args.batch_size)
    print(f"{model.describe()}; warming up with {args.warmup} throwaway queries", flush=True)
    for question in WARMUP_QUESTIONS[: args.warmup]:
        warm, _ = search(args.api, question, args.top)
        model(question, [passage(c.model_dump()) for c in warm])

    print("Timing the reranker, one query at a time ...", flush=True)
    rows = []
    for number, (item, chunks, search_ms) in enumerate(fetched, 1):
        started = time.perf_counter()
        scores = model(item["question"], [passage(c.model_dump()) for c in chunks])
        rerank_ms = (time.perf_counter() - started) * 1000
        timed_out = rerank_ms > args.timeout_ms
        print(f"[{number}/{len(fetched)}] {item['id']}: rerank {rerank_ms:,.0f} ms", flush=True)
        a = chunks
        b_nt = reorder(chunks, scores)
        c_nt = weighted(b_nt, item["question"], chunks)
        c_fb = weighted(chunks, item["question"], chunks)  # the weighted score without the reranker
        rows.append(
            {
                "item": item,
                "search_ms": search_ms,
                "rerank_ms": rerank_ms,
                "timed_out": timed_out,
                "orders": {
                    "A": a,
                    "B_nt": b_nt,
                    "B": a if timed_out else b_nt,
                    "C_nt": c_nt,
                    "C": c_fb if timed_out else c_nt,
                },
            }
        )

    arms = ("A", "B", "C", "B_nt", "C_nt")
    summary: dict[str, dict] = {}
    per_question = []
    for arm in arms:
        scored = []
        totals = []
        for row in rows:
            targets = [Target.parse(t) for t in row["item"].get("relevant", [])]
            if row["item"].get("answerable", True) and targets:
                scored.append(score_retrieval(hits_of(row["orders"][arm]), targets, ks=KS))
            capped = min(row["rerank_ms"], args.timeout_ms)
            if arm == "A":
                totals.append(row["search_ms"])
            elif arm.endswith("_nt"):
                totals.append(row["search_ms"] + row["rerank_ms"])
            else:
                totals.append(row["search_ms"] + capped)
        summary[arm] = {
            "questions_scored": len(scored),
            "recall@5": mean(r.recall_at[5] for r in scored),
            "recall@20": mean(r.recall_at[20] for r in scored),
            "ndcg@10": mean(r.ndcg_at[10] for r in scored),
            "mrr": mean(r.reciprocal_rank for r in scored),
            "hit@1": mean(r.hit_at[1] for r in scored),
            "hit@20": mean(r.hit_at[20] for r in scored),
            "total_p50_ms": percentile(totals, 50),
            "total_p95_ms": percentile(totals, 95),
            "degraded_rate": (
                0.0
                if arm in ("A", "B_nt", "C_nt")
                else mean(1.0 if r["timed_out"] else 0.0 for r in rows)
            ),
        }
    for row in rows:
        per_question.append(
            {
                "id": row["item"]["id"],
                "search_ms": round(row["search_ms"]),
                "rerank_ms": round(row["rerank_ms"]),
                "timed_out": row["timed_out"],
            }
        )
    rerank_ms = [r["rerank_ms"] for r in rows]
    report = {
        "reranker": model.describe(),
        "timeout_ms": args.timeout_ms,
        "arms": summary,
        "rerank_p50_ms": percentile(rerank_ms, 50),
        "rerank_p95_ms": percentile(rerank_ms, 95),
        "per_question": per_question,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report written to {args.out}")
    for arm in arms:
        print(arm, {k: round(v, 3) for k, v in summary[arm].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
