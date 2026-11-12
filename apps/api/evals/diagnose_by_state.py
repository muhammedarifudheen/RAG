"""The 25 retrieval-scored golden questions broken down by expected state (KNOWN, INFERRED,
PARTIAL): is a low overall hit@1 a retrieval failure, or set composition?

Two views of the same questions: the candidate order `/search` returns (top 20), and the `/ask`
pipeline's retrieval (production arm of the interleaved repeat, `reports/ab_repeat.json`, averaged
over its rounds). Each is scored by chunk (a hit must overlap a target's lines) and by file (any
chunk of a target's file), to separate retrieval from the line-range strictness of the labels.

    python -m evals.diagnose_by_state --api https://atlas-api-uxze.onrender.com
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.ab_arms import hits_of, search
from evals.metrics import Target, mean, score_retrieval
from evals.run_evals import load_golden

HERE = Path(__file__).resolve().parent
BUCKETS = ("1", "2-5", "6-10", "11-20", "absent")


def bucket(rank: int | None) -> str:
    if rank is None:
        return "absent"
    return "1" if rank == 1 else "2-5" if rank <= 5 else "6-10" if rank <= 10 else "11-20"


def by_file(targets: list[Target]) -> list[Target]:
    """The same targets with their line ranges dropped: any chunk of the file counts."""
    return list({t.file: Target(t.file) for t in targets}.values())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--golden", type=Path, default=HERE / "golden" / "golden_set.jsonl")
    p.add_argument("--repeat", type=Path, default=HERE / "reports" / "ab_repeat.json")
    p.add_argument("--out", type=Path, default=HERE / "reports" / "by_state.json")
    args = p.parse_args(argv)

    raw = {
        json.loads(line)["id"]: json.loads(line)
        for line in args.golden.read_text("utf-8").splitlines()
        if line.strip()
    }
    asked: dict[str, list[dict]] = defaultdict(list)
    if args.repeat.exists():
        for rnd in json.loads(args.repeat.read_text("utf-8"))["rows"]["production"]:
            for row in rnd:
                asked[row["id"]].append(row)

    groups: dict[str, list[dict]] = defaultdict(list)
    for item in load_golden(args.golden):
        targets = [Target.parse(t) for t in item.get("relevant", [])]
        if not item.get("answerable", True) or not targets:
            continue
        chunks, _ = search(args.api, item["question"], 20)
        hits = hits_of(chunks)
        chunk = score_retrieval(hits, targets, ks=(1, 5, 10, 20))
        file_level = score_retrieval(hits, by_file(targets), ks=(1, 5, 10, 20))
        ranks = [
            r
            for r in (
                next((i for i, h in enumerate(hits, 1) if h.file.endswith(t.file)), None)
                for t in by_file(targets)
            )
            if r
        ]
        first_file = min(ranks) if ranks else None
        first_chunk = next(
            (i for i, h in enumerate(hits, 1) if any(_m(h, t) for t in targets)), None
        )
        ask_rows = asked.get(item["id"], [])
        groups[raw[item["id"]]["expected_state"]].append(
            {
                "id": item["id"],
                "paths": len(targets),
                "hit@1": chunk.hit_at[1],
                "hit@1_file": file_level.hit_at[1],
                "ndcg@10": chunk.ndcg_at[10],
                "recall@20": chunk.hit_at[20],
                "recall@20_file": file_level.hit_at[20],
                "first_rank": first_chunk,
                "first_rank_file": first_file,
                "ask_hit@1": mean(r["hit@1"] for r in ask_rows) if ask_rows else None,
                "ask_ndcg@10": mean(r["ndcg@10"] for r in ask_rows) if ask_rows else None,
            }
        )

    def summarise(rows: list[dict]) -> dict:
        hist = {b: 0 for b in BUCKETS}
        hist_file = {b: 0 for b in BUCKETS}
        for r in rows:
            hist[bucket(r["first_rank"])] += 1
            hist_file[bucket(r["first_rank_file"])] += 1
        asked_rows = [r for r in rows if r["ask_hit@1"] is not None]
        return {
            "questions": len(rows),
            "mean_paths": mean(r["paths"] for r in rows),
            "search": {
                "hit@1": mean(r["hit@1"] for r in rows),
                "hit@1_file": mean(r["hit@1_file"] for r in rows),
                "ndcg@10": mean(r["ndcg@10"] for r in rows),
                "recall@20": mean(r["recall@20"] for r in rows),
                "recall@20_file": mean(r["recall@20_file"] for r in rows),
                "first_rank": hist,
                "first_rank_file": hist_file,
            },
            "ask": {
                "hit@1": mean(r["ask_hit@1"] for r in asked_rows) if asked_rows else None,
                "ndcg@10": mean(r["ask_ndcg@10"] for r in asked_rows) if asked_rows else None,
            },
        }

    everything = [r for rows in groups.values() for r in rows]
    report = {state: summarise(rows) for state, rows in sorted(groups.items())}
    report["ALL"] = summarise(everything)
    report["rows"] = everything
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
    return 0


def _m(hit, target) -> bool:
    from evals.metrics import matches

    return matches(hit, target)


if __name__ == "__main__":
    raise SystemExit(main())
