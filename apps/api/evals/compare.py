"""Two eval reports side by side, with the change in each metric.

    python -m evals.compare legacy.json weighted.json

The first is the baseline, the second the candidate; a delta is candidate minus baseline,
and each is marked better (+) or worse (-) by the direction that is good for that metric.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evals.run_evals import LOWER_IS_BETTER

# The headline metrics first, in the order the ship decision reads them.
HEADLINE = ("recall@5", "ndcg@10", "mrr", "latency_p50_ms", "latency_p95_ms")


def load(path: str) -> dict[str, float]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("summary", data)


def table(base: dict[str, float], new: dict[str, float]) -> list[str]:
    names = [n for n in HEADLINE if n in base and n in new]
    names += sorted(n for n in base if n in new and n not in HEADLINE and n not in ("questions",))
    lines = [f"{'metric':<26}{'baseline':>12}{'candidate':>12}{'delta':>12}"]
    for name in names:
        a, b = base[name], new[name]
        delta = b - a
        timing = name.endswith("_ms")
        worse = delta > 0 if name in LOWER_IS_BETTER else delta < 0
        mark = "" if abs(delta) < 1e-9 else (" -" if worse else " +")
        fmt = (lambda v: f"{v:,.0f} ms") if timing else (lambda v: f"{v:.3f}")
        sign = f"{delta:+,.0f} ms" if timing else f"{delta:+.3f}"
        lines.append(f"{name:<26}{fmt(a):>12}{fmt(b):>12}{sign + mark:>12}")
    return lines


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__)
        return 2
    print("\n".join(table(load(args[0]), load(args[1]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
