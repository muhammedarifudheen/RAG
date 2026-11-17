"""Measures the relevance gate: the best judge score each question gets, and where to set the
gate so that most questions the knowledge base can answer pass it.

    python -m evals.calibrate_gate --api https://atlas-api.example.com

It asks each question of `golden/gate.jsonl` with `retrieval_only` (retrieval and judging, no
answer is written, so a run is minutes, not hours) and `low_confidence_path` off, so what it
sees is what the gates alone do. For every question it logs the gate, the judge cut-off, the
best judge score, the best cosine similarity and how many excerpts survived.

The gate is then set at the 20th percentile of the best scores of the answerable questions: 80%
of them pass it, and the lowest fifth are the ones flagged low confidence. The report shows
what that gate would do to the questions the knowledge base cannot answer (how many would
pass it too), because a gate that lets those through is no gate. The judge's scores are
integers from an LLM, not a calibrated probability, so read the table, not just the number.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.metrics import percentile

HERE = Path(__file__).resolve().parent


def ask(base: str, question: str, timeout: float) -> dict:
    body = {
        "question": question,
        "retrieval_only": True,
        "low_confidence_path": False,
        "web_search": False,
        "cache": False,
    }
    request = urllib.request.Request(
        f"{base}/ask",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def observe(data: dict) -> dict:
    """What one question's response says about the gates."""
    rerank = data.get("reranking") or {}
    return {
        "top_score": rerank.get("top_score"),
        "top_similarity": rerank.get("top_similarity"),
        "scores": rerank.get("scores") or [],
        "judged": rerank.get("judged"),
        "candidates": rerank.get("candidates"),
        "kept": rerank.get("kept"),
        "cutoff": rerank.get("cutoff"),
        "gate": rerank.get("gate"),
        "degraded": bool(data.get("degraded")),
    }


def spread(values: list[float]) -> dict:
    if not values:
        return {}
    return {
        "n": len(values),
        "min": min(values),
        "p10": percentile(values, 10),
        "p20": percentile(values, 20),
        "median": percentile(values, 50),
        "max": max(values),
    }


def passing(values: list[float], gate: float) -> float:
    return sum(1 for v in values if v >= gate) / len(values) if values else 0.0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--golden", type=Path, default=HERE / "golden" / "gate.jsonl")
    p.add_argument("--timeout", type=float, default=180)
    p.add_argument("--delay", type=float, default=1.0, help="seconds between questions")
    p.add_argument("--percentile", type=float, default=20, help="the gate, as a percentile")
    p.add_argument("--out", type=Path, help="write the observations here (JSON)")
    args = p.parse_args(argv)

    questions = [
        json.loads(line)
        for line in args.golden.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    rows = []
    for number, item in enumerate(questions, 1):
        started = time.perf_counter()
        try:
            seen = observe(ask(args.api.rstrip("/"), item["question"], args.timeout))
            error = None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            seen, error = {}, f"{type(exc).__name__}: {exc}"
        row = {
            "id": item["id"],
            "answerable": item.get("answerable", True),
            "question": item["question"],
            "error": error,
            "seconds": round(time.perf_counter() - started, 1),
            **seen,
        }
        rows.append(row)
        print(
            f"[{number:>2}/{len(questions)}] {'answerable  ' if row['answerable'] else 'unanswerable'}"
            f"  gate={row.get('gate')} cutoff={row.get('cutoff')} "
            f"top_score={row.get('top_score')} top_sim={_fmt(row.get('top_similarity'))} "
            f"kept={row.get('kept')}/{row.get('candidates')}  {item['id']}"
            + (f"  ERROR {error}" if error else ""),
            flush=True,
        )
        time.sleep(args.delay)

    scored = [r for r in rows if not r["error"] and r.get("top_score") is not None]
    yes = [r["top_score"] for r in scored if r["answerable"]]
    no = [r["top_score"] for r in scored if not r["answerable"]]
    yes_sim = [r["top_similarity"] for r in scored if r["answerable"] and r["top_similarity"]]
    no_sim = [r["top_similarity"] for r in scored if not r["answerable"] and r["top_similarity"]]

    print(f"\n{len(rows)} questions, {len(rows) - len(scored)} without a judge score\n")
    print("Best judge score (0-10):")
    print("  answerable  ", spread(yes))
    print("  unanswerable", spread(no))
    print("Best cosine similarity:")
    print("  answerable  ", {k: round(v, 3) for k, v in spread(yes_sim).items()})
    print("  unanswerable", {k: round(v, 3) for k, v in spread(no_sim).items()})

    print("\nIf the gate were...   answerable pass   unanswerable pass (false accepts)")
    for g in range(11):
        print(f"  {g:>2}                  {passing(yes, g):>6.0%}            {passing(no, g):>6.0%}")

    gate = round(percentile(yes, args.percentile)) if yes else None
    print(f"\nThe {args.percentile:.0f}th percentile of the answerable questions' best scores: "
          f"{percentile(yes, args.percentile):.2f}  ->  gate {gate}")
    if gate is not None:
        print(
            f"At gate {gate}: {passing(yes, gate):.0%} of answerable questions pass; "
            f"{passing(no, gate):.0%} of unanswerable ones pass too."
        )
    if args.out:
        args.out.write_text(json.dumps({"rows": rows, "gate": gate}, indent=2) + "\n", "utf-8")
        print(f"Observations written to {args.out}")
    return 0


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


if __name__ == "__main__":
    sys.exit(main())
