"""Is the bottleneck retrieval (the right file never reaches the top 20) or ranking (it reaches
the top 20 but not the top)? Per question with a retrieval target: recall@20, hit@1 and the rank
of the first relevant chunk, from `/search` (the candidate order, no reranking).

    python -m evals.diagnose_bottleneck --api https://atlas-api-uxze.onrender.com \\
        --out evals/reports/bottleneck.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.ab_arms import hits_of, search
from evals.metrics import Target, found_at
from evals.run_evals import load_golden

HERE = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--golden", type=Path, default=HERE / "golden" / "golden_set.jsonl")
    p.add_argument("--out", type=Path, default=HERE / "reports" / "bottleneck.json")
    args = p.parse_args(argv)

    rows = []
    for item in load_golden(args.golden):
        targets = [Target.parse(t) for t in item.get("relevant", [])]
        if not item.get("answerable", True) or not targets:
            continue
        chunks, _ = search(args.api, item["question"], 20)
        hits = hits_of(chunks)
        ranks = [r for r in (found_at(hits, t) for t in targets) if r is not None]
        first = min(ranks) if ranks else None
        rows.append(
            {
                "id": item["id"],
                "retrieved": len(hits),
                "recall@20": 1.0 if first else 0.0,
                "hit@1": 1.0 if first == 1 else 0.0,
                "first_rank": first,
                "targets": [str(t) for t in targets],
            }
        )
        print(item["id"], "first rank:", first or "absent", flush=True)

    found = [r for r in rows if r["recall@20"]]
    summary = {
        "questions": len(rows),
        "found_in_top20": len(found) / len(rows),
        "hit@1_given_found": sum(r["hit@1"] for r in found) / len(found) if found else 0.0,
        "hit@1_overall": sum(r["hit@1"] for r in rows) / len(rows),
        "never_found": 1 - len(found) / len(rows),
        "first_rank_distribution": {
            "1": sum(1 for r in found if r["first_rank"] == 1),
            "2-5": sum(1 for r in found if 2 <= r["first_rank"] <= 5),
            "6-10": sum(1 for r in found if 6 <= r["first_rank"] <= 10),
            "11-20": sum(1 for r in found if r["first_rank"] > 10),
        },
    }
    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
