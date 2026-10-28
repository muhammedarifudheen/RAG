"""Finding the code a chat message asks to review, and turning an analysis into the
API's shape and into text for the agents."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence

import httpx2

from app.schemas import (
    Attachment,
    CodeAnalysis,
    CodeFinding,
    FileRiskOut,
    FunctionMetricOut,
    ImportCount,
)

from .repo import RepoReport, findings_line
from .static import Analysis

logger = logging.getLogger("atlas.api.analysis")

_REVIEW = re.compile(
    r"\b(review|analy[sz]e|analysis|audit|inspect|lint|code smells?|"
    r"find (?:any |the |all )?(?:bugs?|issues|problems|vulnerabilit\w*|mistakes)|"
    r"security (?:issues|holes|review|audit|problems)|vulnerabilit\w*|"
    r"what(?:'s| is) wrong|improve (?:this|my|the) code|refactor|code quality)\b",
    re.IGNORECASE,
)
# A repository itself, not a file or folder in it.
_REPO = re.compile(
    r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9._-]+)/?(?=$|[\s)\]>,!?;:'\"])"
)
_BLOB = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/blob/([^/\s]+)/([^\s)\]>#?]+)")
_FENCE = re.compile(r"```([\w+#.-]*)[^\n]*\n(.*?)```", re.DOTALL)
_EXTENSIONS = {
    "python": "py", "py": "py", "typescript": "ts", "ts": "ts", "tsx": "tsx",
    "javascript": "js", "js": "js", "jsx": "jsx", "go": "go", "golang": "go", "java": "java",
    "kotlin": "kt", "ruby": "rb", "php": "php", "rust": "rs", "c": "c", "cpp": "cpp",
    "c++": "cpp", "csharp": "cs", "c#": "cs", "cs": "cs", "swift": "swift", "sql": "sql",
    "bash": "sh", "sh": "sh", "shell": "sh", "yaml": "yaml", "yml": "yaml", "json": "json",
}  # fmt: skip
MAX_FETCHED = 5


def repo_url(question: str) -> str | None:
    found = _REPO.search(question)
    if not found:
        return None
    # "…/flask." at the end of a sentence; "socket.io" keeps its dot.
    name = found.group(2).rstrip(".").removesuffix(".git")
    return f"https://github.com/{found.group(1)}/{name}" if name else None


def _guess(code: str) -> str:
    if re.search(r"^\s*(def |class |import |from \w+ import)", code, re.MULTILINE):
        return "py"
    if re.search(r"^\s*package \w+|^\s*func ", code, re.MULTILINE):
        return "go"
    if re.search(r"\b(const|let|function|=>|interface|export)\b", code):
        return "ts"
    return "txt"


def code_files(
    question: str,
    attachments: Sequence[Attachment],
    fetch: Callable[[str], str] | None = None,
) -> dict[str, str]:
    """{name: code} from attached files, fenced blocks in the question, and links to
    files on GitHub (fetched with `fetch`)."""
    files: dict[str, str] = {}
    for attachment in attachments:
        if attachment.kind == "text" and attachment.text:
            files[attachment.name.replace("\\", "/").lstrip("/")] = attachment.text
    for n, (tag, code) in enumerate(_FENCE.findall(question), 1):
        extension = _EXTENSIONS.get(tag.lower()) or _guess(code)
        files[f"snippet-{n}.{extension}"] = code
    if fetch is not None:
        for owner, repo, ref, path in _BLOB.findall(question)[:MAX_FETCHED]:
            raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
            try:
                files[path] = fetch(raw)
            except (httpx2.HTTPError, ValueError) as error:
                logger.info("review: could not read %s (%s)", raw, error)
    return files


def wants_review(question: str, has_code: bool) -> bool:
    """A request to review, audit or analyse code that is attached, pasted or linked."""
    return bool(_REVIEW.search(question)) and (has_code or repo_url(question) is not None)


def to_schema(
    analysis: Analysis, report: RepoReport | None = None, limit: int = 300
) -> CodeAnalysis:
    functions = sorted(analysis.functions, key=lambda m: (-m.complexity, -m.nesting))[:20]
    return CodeAnalysis(
        repo=report.repo if report else None,
        commit=report.commit if report else None,
        files=analysis.files,
        lines=analysis.lines,
        code_lines=analysis.code_lines,
        languages=analysis.languages,
        score=analysis.score,
        grade=analysis.grade,
        counts=analysis.counts,
        findings=[
            CodeFinding(
                tool=f.tool,
                rule=f.rule,
                severity=f.severity,
                path=f.path,
                line=f.line,
                message=f.message,
            )
            for f in analysis.findings[:limit]
        ],
        functions=[
            FunctionMetricOut(
                path=m.path,
                name=m.name,
                start_line=m.start_line,
                end_line=m.end_line,
                complexity=m.complexity,
                nesting=m.nesting,
            )
            for m in functions
        ],
        test_files=report.test_files if report else None,
        cycles=report.cycles[:20] if report else [],
        most_imported=[
            ImportCount(path=p, imported_by=n) for p, n in (report.most_imported if report else [])
        ],
        riskiest=[
            FileRiskOut(
                path=r.path,
                lines=r.lines,
                findings=r.findings,
                complexity=r.complexity,
                imported_by=r.imported_by,
                risk=r.risk,
            )
            for r in (report.riskiest if report else [])
        ],
        seconds=report.seconds if report else None,
    )


def files_summary(analysis: Analysis, limit: int = 60) -> str:
    """The analysis of pasted or attached code, as text for the agents."""
    counts = analysis.counts
    lines = [
        "<static_analysis>",
        (
            f"{analysis.files} file(s), {analysis.code_lines or analysis.lines} lines of code. "
            f"Score {analysis.score}/100 (grade {analysis.grade}); findings: "
            f"{counts['high']} high, {counts['medium']} medium, {counts['low']} low."
        ),
    ]
    functions = sorted(analysis.functions, key=lambda m: -m.complexity)[:10]
    if functions:
        lines.append("Functions by complexity:")
        lines += [
            f"- {m.path}:{m.start_line}-{m.end_line} {m.name}: complexity {m.complexity}, "
            f"nesting {m.nesting}"
            for m in functions
        ]
    if analysis.findings:
        lines.append("Findings (most severe first):")
        lines += [findings_line(f) for f in analysis.findings[:limit]]
    else:
        lines.append("The checks found nothing; review the code's logic and design yourself.")
    lines.append("</static_analysis>")
    return "\n".join(lines)
