"""A whole repository's analysis: clone it (shallow, nothing stored), run every check
in static.py, link its imports to find dependency cycles and the most depended-on
files, and rank the files where problems and complexity meet."""

from __future__ import annotations

import logging
import math
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .static import (
    _WEIGHT,
    TEXT_SUFFIXES,
    Analysis,
    Finding,
    FunctionMetric,
    complexity_findings,
    family_of,
    for_tests,
    is_code,
    is_test,
    measure,
    ruff,
    scan_patterns,
    scan_secrets,
)

logger = logging.getLogger("atlas.api.analysis")

# Folders of other people's code, build output and tooling.
SKIP_DIRS = frozenset(
    {
        ".git", "node_modules", "vendor", "third_party", "third-party", "dist", "build", "out",
        "target", ".next", ".nuxt", "coverage", "__pycache__", ".venv", "venv", "env",
        ".tox", ".mypy_cache", ".ruff_cache", ".pytest_cache", "site-packages", "bower_components",
        ".idea", ".vscode", "Pods", ".gradle", "migrations_old",
    }
)  # fmt: skip
MAX_FILE_BYTES = 400_000
# Generated dependency lists: long, and not anyone's code.
LOCK_FILES = frozenset(
    {"pnpm-lock.yaml", "package-lock.json", "yarn.lock", "poetry.lock", "Cargo.lock",
     "go.sum", "uv.lock", "Pipfile.lock", "composer.lock", "Gemfile.lock", "bun.lock"}
)  # fmt: skip
MAX_FILES = 4000
MAX_TOTAL_BYTES = 60_000_000


class RepoTooLarge(Exception):
    pass


@dataclass
class FileRisk:
    path: str
    lines: int
    findings: int
    weight: float  # findings, by severity
    complexity: int  # the most complex function in it
    imported_by: int  # files that import it
    risk: float


@dataclass
class RepoReport:
    repo: str
    commit: str
    analysis: Analysis
    test_files: int = 0
    cycles: list[list[str]] = field(default_factory=list)
    most_imported: list[tuple[str, int]] = field(default_factory=list)
    riskiest: list[FileRisk] = field(default_factory=list)
    largest: list[tuple[str, int]] = field(default_factory=list)
    skipped: int = 0  # files too large, minified or past the limit
    # The most complex functions' code, for the agents to read.
    excerpts: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0


Progress = Callable[[str], None]


def _minified(text: str) -> bool:
    lines = text.count("\n") + 1
    return len(text) / lines > 300


def source_files(root: Path) -> Iterator[tuple[str, Path, int]]:
    """(relative POSIX path, path, size) of each text file worth analysing."""
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(names):
            path = Path(folder) / name
            if name in LOCK_FILES or (
                PurePosixPath(name).suffix.lower() not in TEXT_SUFFIXES and name != "Dockerfile"
            ):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            yield path.relative_to(root).as_posix(), path, size


def _go_modules(files: dict[str, str]) -> dict[str, str]:
    modules = {}
    for path, text in files.items():
        if PurePosixPath(path).name == "go.mod":
            found = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
            if found:
                parent = PurePosixPath(path).parent.as_posix()
                modules["" if parent == "." else parent] = found.group(1)
    return modules


def import_graph(files: dict[str, str]) -> dict[str, set[str]]:
    """File -> the files it imports, for Python, TypeScript/JavaScript and Go, using the
    same parser and resolver as ingestion."""
    from worker.extract import extract_source, language_for
    from worker.resolve import IMPORTS, resolve

    extractions = []
    for path, text in files.items():
        if language_for(path) is None:
            continue
        try:
            extractions.append(extract_source(path, text.encode("utf-8", "replace")))
        except (ValueError, RuntimeError, RecursionError) as error:
            logger.info("analysis: could not parse %s (%s)", path, error)
    graph: dict[str, set[str]] = {}
    for edge in resolve(extractions, _go_modules(files)):
        if edge.kind == IMPORTS and edge.src.path != edge.dst.path:
            graph.setdefault(edge.src.path, set()).add(edge.dst.path)
    return graph


def cycles_of(graph: dict[str, set[str]]) -> list[list[str]]:
    from app.services.health import strongly_connected

    ids = {
        path: n
        for n, path in enumerate(sorted({*graph, *(t for ts in graph.values() for t in ts)}))
    }
    paths = {n: path for path, n in ids.items()}
    edges = [(ids[s], ids[t]) for s, targets in graph.items() for t in targets]
    groups = [sorted(paths[n] for n in group) for group in strongly_connected(edges)]
    return sorted(groups, key=lambda g: (-len(g), g))


def analyse_tree(root: Path, progress: Progress = lambda _: None) -> RepoReport:
    """Every check on a checked-out repository at `root`."""
    started = time.monotonic()
    report = RepoReport(repo="", commit="", analysis=Analysis())
    analysis = report.analysis
    files: dict[str, str] = {}
    total = 0
    for relative, path, size in source_files(root):
        if size > MAX_FILE_BYTES or len(files) >= MAX_FILES:
            report.skipped += 1
            continue
        total += size
        if total > MAX_TOTAL_BYTES:
            raise RepoTooLarge(
                f"The repository has over {MAX_TOTAL_BYTES // 1_000_000} MB of code to read; "
                "analyse a smaller one."
            )
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _minified(text):
            report.skipped += 1
            continue
        files[relative] = text
    progress(f"Reading {len(files)} files")

    per_file_functions: dict[str, list[FunctionMetric]] = {}
    for relative, text in files.items():
        lines = text.count("\n") + 1
        language = family_of(relative) or (PurePosixPath(relative).suffix.lstrip(".") or "text")
        analysis.files += 1
        analysis.lines += lines
        if is_code(relative):
            analysis.code_lines += lines
        analysis.languages[language] = analysis.languages.get(language, 0) + lines
        analysis.findings += scan_secrets(relative, text)
        if family_of(relative):
            analysis.findings += scan_patterns(relative, text)
            metrics = measure(relative, text)
            per_file_functions[relative] = metrics
            analysis.functions += metrics
            analysis.findings += complexity_findings(metrics)
        if is_test(relative):
            report.test_files += 1

    progress("Running Ruff on the Python code")
    analysis.findings += [f for f in ruff(root) if f.path in files]
    analysis.findings = for_tests(analysis.findings)
    analysis.findings.sort(key=lambda f: (-_WEIGHT[f.severity], f.path, f.line))

    progress("Linking imports")
    graph = import_graph(files)
    report.cycles = cycles_of(graph)
    imported_by: dict[str, int] = {}
    for targets in graph.values():
        for target in targets:
            imported_by[target] = imported_by.get(target, 0) + 1
    report.most_imported = sorted(imported_by.items(), key=lambda kv: (-kv[1], kv[0]))[:15]

    weights: dict[str, tuple[int, float]] = {}
    for finding in analysis.findings:
        count, weight = weights.get(finding.path, (0, 0.0))
        weights[finding.path] = (count + 1, weight + _WEIGHT[finding.severity])
    risks = []
    for relative, text in files.items():
        count, weight = weights.get(relative, (0, 0.0))
        worst = max((m.complexity for m in per_file_functions.get(relative, [])), default=0)
        fan_in = imported_by.get(relative, 0)
        risk = (weight + max(0, worst - 10)) * (1 + math.log2(1 + fan_in))
        if risk > 0:
            lines = text.count("\n") + 1
            risks.append(FileRisk(relative, lines, count, weight, worst, fan_in, round(risk, 1)))
    report.riskiest = sorted(risks, key=lambda r: -r.risk)[:15]
    report.largest = sorted(
        ((p, t.count("\n") + 1) for p, t in files.items() if family_of(p)), key=lambda kv: -kv[1]
    )[:10]
    for m in sorted(analysis.functions, key=lambda m: -m.complexity)[:6]:
        body = files[m.path].splitlines()[m.start_line - 1 : m.end_line]
        cut = body[:80] + (["    ... (cut)"] if len(body) > 80 else [])
        report.excerpts[f"{m.path}:{m.start_line}-{m.end_line} {m.name}"] = "\n".join(cut)
    report.seconds = round(time.monotonic() - started, 1)
    return report


def analyse_repo(url: str, progress: Progress = lambda _: None) -> RepoReport:
    """Clones a public GitHub repository (latest commit only), analyses it, deletes it."""
    from worker.clone import clone_repo, remove_clone

    progress("Cloning the repository")
    cloned = clone_repo(url)
    try:
        report = analyse_tree(cloned.path, progress)
    finally:
        remove_clone(cloned.path)
    report.repo = url.rstrip("/").removesuffix(".git")
    report.commit = cloned.commit
    return report


def summary_for_agents(report: RepoReport, limit: int = 60) -> str:
    """The report as text for the assistant's agents to review."""
    a = report.analysis
    counts = a.counts
    languages = ", ".join(
        f"{lang} {lines:,} lines"
        for lang, lines in sorted(a.languages.items(), key=lambda kv: -kv[1])
    )
    lines = [
        f'<repository_analysis repo="{report.repo}" commit="{report.commit[:12]}">',
        f"Files analysed: {a.files} ({a.lines:,} lines; {languages}). Test files: {report.test_files}.",
        (
            f"Score {a.score}/100 (grade {a.grade}); findings: {counts['high']} high, "
            f"{counts['medium']} medium, {counts['low']} low."
        ),
    ]
    if report.cycles:
        lines.append("Import cycles:")
        lines += [f"- {' -> '.join(group)}" for group in report.cycles[:8]]
    if report.riskiest:
        lines.append(
            "Riskiest files (findings and complexity, weighted by how many files import them):"
        )
        lines += [
            f"- {r.path}: {r.findings} findings, worst function complexity {r.complexity}, "
            f"imported by {r.imported_by}"
            for r in report.riskiest[:10]
        ]
    complex_functions = sorted(a.functions, key=lambda m: -m.complexity)[:10]
    if complex_functions:
        lines.append("Most complex functions:")
        lines += [
            f"- {m.path}:{m.start_line}-{m.end_line} {m.name}: complexity {m.complexity}, "
            f"nesting {m.nesting}"
            for m in complex_functions
        ]
    lines.append("Findings (most severe first):")
    lines += [findings_line(f) for f in a.findings[:limit]]
    if len(a.findings) > limit:
        lines.append(f"... and {len(a.findings) - limit} more.")
    for where, code in report.excerpts.items():
        lines.append(f"Code of {where}:\n```\n{code}\n```")
    lines.append("</repository_analysis>")
    return "\n".join(lines)


def findings_line(f: Finding) -> str:
    return f"- [{f.severity}] {f.path}:{f.line} {f.tool} {f.rule}: {f.message}"
