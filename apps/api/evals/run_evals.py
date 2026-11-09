"""Runs the golden questions against a running Atlas API and reports retrieval and answer
quality. Standard library only, so it runs anywhere: against a local API, staging or the
public server.

    python -m evals.run_evals --api http://localhost:8000 --mode search
    python -m evals.run_evals --mode ask --out evals/report.json
    python -m evals.run_evals --mode ask --baseline evals/baseline.json --max-drop 0.05

Modes:
  search  GET /search: vector search alone. No model is called, so it is free and fast;
          use it to compare embedding models and chunking.
  ask     POST /ask: the whole pipeline (planner, hybrid search, reranking, the answer).
          Retrieval is scored on the excerpts given to the model, and the answer on its
          citations, required phrases and, for unanswerable questions, declining.

Exit status 1 if a metric falls more than --max-drop below the baseline, or under a --min
floor; 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if __package__ in (None, ""):  # run as a script: put the API root on the path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.metrics import (
    KS,
    Hit,
    Target,
    citation_precision,
    declined,
    mean,
    must_include_coverage,
    percentile,
    score_retrieval,
)
from evals.rerank import DEFAULT_MODEL, make_reranker, rerank_top

HERE = Path(__file__).resolve().parent


def load_golden(path: Path) -> list[dict]:
    items = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip() and not line.lstrip().startswith("#"):
            try:
                items.append(normalise(json.loads(line)))
            except json.JSONDecodeError as error:
                raise SystemExit(f"{path}:{number}: not valid JSON ({error})") from error
    return items


# States for which the right behaviour is to decline: nothing in the knowledge base answers.
DECLINING_STATES = {"ABSENT", "REFUSED"}


def normalise(item: dict) -> dict:
    """Accepts both golden-set spellings: `relevant` / `answerable`, and `relevant_paths` /
    `expected_state` (ABSENT and REFUSED mean there is nothing to find, so not answerable)."""
    if "relevant" not in item:
        item["relevant"] = item.get("relevant_paths", [])
    if "answerable" not in item and "expected_state" in item:
        item["answerable"] = item["expected_state"].upper() not in DECLINING_STATES
    return item


def call(url: str, *, body: dict | None, token: str | None, timeout: float) -> dict:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def run_one(item: dict, args: argparse.Namespace) -> dict:
    """One question's raw outcome: the excerpts, and in ask mode the answer."""
    base = args.api.rstrip("/")
    started = time.perf_counter()
    out: dict = {"id": item["id"], "question": item["question"], "error": None}
    try:
        if args.mode == "search":
            # A reranker needs its candidates: the top N of the search, not just the top k.
            limit = max(args.k, args.rerank_top) if args.reranker else args.k
            query = urllib.parse.urlencode({"q": item["question"], "limit": limit})
            data = call(f"{base}/search?{query}", body=None, token=args.token, timeout=args.timeout)
            out["chunks"] = data["results"]
            if args.reranker:
                reranked = time.perf_counter()
                out["chunks"] = rerank_top(
                    item["question"], out["chunks"], args.reranker_fn, args.rerank_top
                )
                out["rerank_ms"] = (time.perf_counter() - reranked) * 1000
        else:
            body = {
                "question": item["question"],
                "use_sources": True,
                "web_search": False,  # score the knowledge base, not today's web
                "cache": False,
                "council_size": 1,
                "include_drafts": False,
                "top_k": args.k,
                "plan_queries": not args.no_plan,
                "rerank": not args.no_rerank,
            }
            if args.rank:  # weighted | legacy: the final ranking, to compare the two
                body["weighted_rank"] = args.rank == "weighted"
            data = call(f"{base}/ask", body=body, token=args.token, timeout=args.timeout)
            out.update(
                answer=data.get("answer", ""),
                citations=data.get("citations", []),
                chunks=data.get("chunks", []),
                epistemic=data.get("epistemic"),
                server_ms=data.get("latency_ms"),
                degraded=bool(data.get("degraded")),
            )
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as error:
        out["error"] = f"{type(error).__name__}: {error}"
        out.setdefault("chunks", [])
    out["ms"] = (time.perf_counter() - started) * 1000
    return out


def evaluate(item: dict, raw: dict, args: argparse.Namespace) -> dict:
    """Scores one question."""
    answerable = item.get("answerable", True)
    targets = [Target.parse(t) for t in item.get("relevant", [])]
    hits = [Hit(c["file"], c["start_line"], c["end_line"]) for c in raw["chunks"]]
    row: dict = {
        "id": item["id"],
        "answerable": answerable,
        "ms": round(raw["ms"]),
        "error": raw["error"],
    }
    if "rerank_ms" in raw:
        row["rerank_ms"] = round(raw["rerank_ms"])
    if answerable and targets and not raw["error"]:
        r = score_retrieval(hits, targets)
        row["mrr"] = r.reciprocal_rank
        for k in KS:
            row[f"hit@{k}"] = r.hit_at[k]
            row[f"recall@{k}"] = r.recall_at[k]
            row[f"ndcg@{k}"] = r.ndcg_at[k]
        row["missed"] = [t.file for t in targets if not any(h.file.endswith(t.file) for h in hits)]
    if args.mode == "ask" and not raw["error"]:
        answer = raw.get("answer", "")
        cites = raw.get("citations", [])
        row["declined"] = declined(answer, raw.get("epistemic"), len(cites))
        row["degraded"] = 1.0 if raw.get("degraded") else 0.0
        if answerable:
            row["coverage"] = must_include_coverage(answer, item.get("must_include", []))
            row["cite_precision"] = citation_precision(cites, targets) if targets else None
            row["cited"] = 1.0 if cites else 0.0
            row["verified_share"] = (
                sum(1 for c in cites if c.get("verified")) / len(cites) if cites else None
            )
    return row


def summarise(rows: list[dict], mode: str) -> dict[str, float]:
    ok = [r for r in rows if not r["error"]]
    scored = [r for r in ok if "mrr" in r]
    summary: dict[str, float] = {"questions": len(rows), "errors": len(rows) - len(ok)}
    for k in KS:
        for name in ("hit", "recall", "ndcg"):
            summary[f"{name}@{k}"] = mean(r.get(f"{name}@{k}") for r in scored)
    summary["mrr"] = mean(r["mrr"] for r in scored)
    summary["latency_p50_ms"] = percentile([r["ms"] for r in ok], 50)
    summary["latency_p95_ms"] = percentile([r["ms"] for r in ok], 95)
    reranked = [r["rerank_ms"] for r in ok if "rerank_ms" in r]
    if reranked:  # the cost of the reranker alone, already inside the latency above
        summary["rerank_p50_ms"] = percentile(reranked, 50)
        summary["rerank_p95_ms"] = percentile(reranked, 95)
    if mode == "ask":
        answerable = [r for r in ok if r["answerable"]]
        unanswerable = [r for r in ok if not r["answerable"]]
        summary["degraded_rate"] = mean(r.get("degraded") for r in ok)
        summary["answer_coverage"] = mean(r.get("coverage") for r in answerable)
        summary["citation_precision"] = mean(r.get("cite_precision") for r in answerable)
        summary["cited_rate"] = mean(r.get("cited") for r in answerable)
        summary["verified_citation_share"] = mean(r.get("verified_share") for r in answerable)
        summary["false_refusal_rate"] = mean(1.0 if r.get("declined") else 0.0 for r in answerable)
        summary["correct_refusal_rate"] = mean(
            1.0 if r.get("declined") else 0.0 for r in unanswerable
        )
    return summary


# Lower is better for these; every other metric is higher-is-better.
LOWER_IS_BETTER = {
    "errors",
    "false_refusal_rate",
    "degraded_rate",
    "latency_p50_ms",
    "latency_p95_ms",
    "rerank_p50_ms",
    "rerank_p95_ms",
}
# Not compared against the baseline (counts and timings vary run to run).
NOT_GATED = {"questions", "latency_p50_ms", "latency_p95_ms", "rerank_p50_ms", "rerank_p95_ms"}


def regressions(summary: dict, baseline: dict, max_drop: float) -> list[str]:
    problems = []
    for name, old in baseline.items():
        if name in NOT_GATED or name not in summary:
            continue
        new = summary[name]
        worse = new - old if name in LOWER_IS_BETTER else old - new
        if worse > max_drop:
            problems.append(f"{name}: {old:.3f} -> {new:.3f}")
    return problems


def floors(summary: dict, minimums: list[str]) -> list[str]:
    problems = []
    for spec in minimums:
        name, _, value = spec.partition("=")
        if name not in summary:
            problems.append(f"{name}: not measured in this mode")
        elif summary[name] < float(value):
            problems.append(f"{name}: {summary[name]:.3f} is under the floor {value}")
    return problems


def print_report(summary: dict, rows: list[dict], mode: str) -> None:
    print(f"\n{summary['questions']} questions, {summary['errors']} errors  (mode: {mode})\n")
    for name, value in summary.items():
        if name in ("questions", "errors"):
            continue
        shown = f"{value:,.0f} ms" if name.endswith("_ms") else f"{value:.3f}"
        print(f"  {name:<26}{shown}")
    weak = [r for r in rows if r.get("missed") or r["error"]]
    if weak:
        print("\nWhere it fell short:")
        for r in weak:
            why = r["error"] or "did not retrieve " + ", ".join(r["missed"])
            print(f"  - {r['id']}: {why}")
    print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--api", default="http://localhost:8000", help="the API's address")
    p.add_argument("--mode", choices=("search", "ask"), default="search")
    p.add_argument("--golden", type=Path, default=HERE / "golden" / "atlas.jsonl")
    p.add_argument("-k", type=int, default=10, help="excerpts to retrieve (default 10)")
    p.add_argument("--limit", type=int, help="only the first N questions")
    p.add_argument("--token", help="a bearer token, if the API needs one")
    p.add_argument("--timeout", type=float, default=120, help="seconds per request")
    p.add_argument("--delay", type=float, default=0, help="seconds between requests")
    p.add_argument("--no-plan", action="store_true", help="ask mode: skip query planning")
    p.add_argument("--no-rerank", action="store_true", help="ask mode: skip the relevance judge")
    p.add_argument(
        "--reranker",
        nargs="?",
        const=DEFAULT_MODEL,
        metavar="MODEL",
        help=f"search mode: rerank the top candidates with a cross-encoder ({DEFAULT_MODEL}) "
        "before scoring; runs on this machine and needs torch and transformers",
    )
    p.add_argument(
        "--reranker-backend",
        choices=("auto", "torch", "onnx", "onnx-int8"),
        default="auto",
        help="auto: torch if it loads, else ONNX Runtime (fp32; onnx-int8 is quantised)",
    )
    p.add_argument("--rerank-top", type=int, default=20, help="candidates the reranker reads")
    p.add_argument("--rerank-max-length", type=int, default=512, help="tokens per pair")
    p.add_argument(
        "--rank",
        choices=("weighted", "legacy"),
        help="ask mode: final ranking (weighted score or the judge order)",
    )
    p.add_argument("--out", type=Path, help="write the full report here (JSON)")
    p.add_argument("--baseline", type=Path, help="a report or summary to compare with")
    p.add_argument("--max-drop", type=float, default=0.05, help="allowed fall per metric")
    p.add_argument(
        "--min", action="append", default=[], metavar="METRIC=VALUE", help="a floor, e.g. hit@5=0.7"
    )
    args = p.parse_args(argv)

    if args.reranker and args.mode != "search":
        p.error("--reranker works on search mode: it reorders what /search returns")
    if args.reranker:
        print(f"Loading {args.reranker} ...", flush=True)
        args.reranker_fn = make_reranker(
            args.reranker, args.rerank_max_length, args.reranker_backend
        )

    golden = load_golden(args.golden)
    if args.limit:
        golden = golden[: args.limit]
    rows = []
    for number, item in enumerate(golden, 1):
        print(f"[{number}/{len(golden)}] {item['id']}", flush=True)
        rows.append(evaluate(item, run_one(item, args), args))
        if args.delay:
            time.sleep(args.delay)

    summary = summarise(rows, args.mode)
    print_report(summary, rows, args.mode)
    if args.out:
        report = {"mode": args.mode, "summary": summary, "questions": rows}
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Report written to {args.out}")

    problems = floors(summary, args.min)
    if args.baseline:
        saved = json.loads(args.baseline.read_text(encoding="utf-8"))
        problems += regressions(summary, saved.get("summary", saved), args.max_drop)
    if summary["errors"] == summary["questions"]:
        problems.append("every request failed; is the API running and reachable?")
    for line in problems:
        print(f"FAIL  {line}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
