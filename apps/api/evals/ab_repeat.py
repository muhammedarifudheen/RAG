"""Repeats the production-order versus weighted-ranking comparison on `/ask`, interleaved, to see
whether a difference is real or noise.

For each round and each question, both arms are asked back to back (the order alternates), so
they meet the same server conditions. Then, per metric:

- each arm's mean per round, and the spread (standard deviation) between rounds: the noise;
- the paired difference weighted minus production, per question (averaged over rounds), its mean,
  a 95% bootstrap interval over questions, and how many questions improved, tied or worsened.

A difference counts as real only if its interval excludes zero and it is larger than the
between-round spread of either arm.

    python -m evals.ab_repeat --api https://atlas-api-uxze.onrender.com --rounds 3 \\
        --golden evals/golden/golden_set.jsonl --out evals/reports/ab_repeat.json
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.run_evals import evaluate, load_golden, run_one, summarise

HERE = Path(__file__).resolve().parent
ARMS = ("production", "weighted")  # the weighted_rank flag off, then on
METRICS = ("recall@5", "ndcg@10", "mrr", "hit@1", "cite_precision", "verified_share")
# The summary key whose spread between rounds is a metric's noise.
NOISE_KEY = {
    "recall@5": "recall@5",
    "ndcg@10": "ndcg@10",
    "mrr": "mrr",
    "hit@1": "hit@1",
    "cite_precision": "citation_precision",
}
SUMMARY_KEYS = (
    "recall@5",
    "ndcg@10",
    "mrr",
    "hit@1",
    "citation_precision",
    "correct_refusal_rate",
    "false_refusal_rate",
    "degraded_rate",
    "latency_p50_ms",
    "latency_p95_ms",
    "first_token_p50_ms",
    "first_token_p95_ms",
    "errors",
)


def paired(
    a: dict[str, list[float | None]], b: dict[str, list[float | None]], seed: int = 7
) -> dict:
    """The paired difference b - a over questions. `a` and `b` map a question id to its value in
    each round (None: no value that round). Each question's difference is the mean over the
    rounds where both arms have a value."""
    diffs = []
    for qid in a.keys() & b.keys():
        pairs = [
            (x, y) for x, y in zip(a[qid], b[qid], strict=False) if x is not None and y is not None
        ]
        if pairs:
            diffs.append(sum(y - x for x, y in pairs) / len(pairs))
    if not diffs:
        return {"n": 0, "mean": None, "ci95": None, "better": 0, "tied": 0, "worse": 0}
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(10_000))
    return {
        "n": len(diffs),
        "mean": sum(diffs) / len(diffs),
        "ci95": (means[250], means[9_749]),
        "better": sum(1 for d in diffs if d > 1e-9),
        "tied": sum(1 for d in diffs if abs(d) <= 1e-9),
        "worse": sum(1 for d in diffs if d < -1e-9),
    }


def spread(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def verdict(result: dict, noise: float) -> str:
    """'real' if the interval excludes zero and the mean beats the between-round noise."""
    lo, hi = result["ci95"] or (None, None)
    if lo is None:
        return "no data"
    if lo > 0 and result["mean"] > noise:
        return "weighted better"
    if hi < 0 and -result["mean"] > noise:
        return "weighted worse"
    return "within noise"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--golden", type=Path, default=HERE / "golden" / "golden_set.jsonl")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--delay", type=float, default=1.0)
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--out", type=Path, default=HERE / "reports" / "ab_repeat.json")
    args = p.parse_args(argv)

    items = load_golden(args.golden)
    base = {
        "api": args.api,
        "mode": "ask",
        "k": 10,
        "token": None,
        "timeout": args.timeout,
        "no_plan": False,
        "no_rerank": False,
        "reranker": None,
        "rank": None,
    }
    rows: dict[str, list[list[dict]]] = {arm: [] for arm in ARMS}
    for rnd in range(1, args.rounds + 1):
        done = {arm: [] for arm in ARMS}
        for number, item in enumerate(items):
            order = ARMS if (number + rnd) % 2 == 0 else ARMS[::-1]  # alternate who goes first
            for arm in order:
                ns = argparse.Namespace(
                    **{**base, "rank": "weighted" if arm == "weighted" else "legacy"}
                )
                done[arm].append(evaluate(item, run_one(item, ns), ns))
                time.sleep(args.delay)
            print(
                f"round {rnd}/{args.rounds} question {number + 1}/{len(items)} {item['id']}",
                flush=True,
            )
        for arm in ARMS:
            rows[arm].append(done[arm])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps({"rounds_done": rnd, "rows": rows}, default=str) + "\n", encoding="utf-8"
        )

    summaries = {arm: [summarise(r, "ask") for r in rows[arm]] for arm in ARMS}
    report: dict = {"rounds": args.rounds, "per_arm": {}, "paired": {}}
    for arm in ARMS:
        report["per_arm"][arm] = {
            k: {
                "mean": statistics.mean(s[k] for s in summaries[arm] if k in s),
                "sd_between_rounds": spread([s[k] for s in summaries[arm] if k in s]),
                "per_round": [s.get(k) for s in summaries[arm]],
            }
            for k in SUMMARY_KEYS
            if all(k in s for s in summaries[arm])
        }
    for metric in METRICS:
        by_arm = {
            arm: {
                row["id"]: [rows[arm][r][qi].get(metric) for r in range(len(rows[arm]))]
                for qi, row in enumerate(rows[arm][0])
            }
            for arm in ARMS
        }
        result = paired(by_arm["production"], by_arm["weighted"])
        key = NOISE_KEY.get(metric)
        result["noise_sd"] = (
            max(spread([s[key] for s in summaries[arm] if key in s]) for arm in ARMS)
            if key
            else 0.0
        )
        result["verdict"] = verdict(result, result["noise_sd"])
        report["paired"][metric] = result
    report["rows"] = rows
    args.out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report["paired"], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
