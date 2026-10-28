"""Checks run on source files, with no AI involved: Ruff's lint and security rules on
Python, a scan for leaked secrets, risky patterns in JavaScript, TypeScript and Go, and
each function's size, branching (cyclomatic complexity) and nesting, measured on its
syntax tree. The assistant's agents review what these find."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path, PurePosixPath

logger = logging.getLogger("atlas.api.analysis")

HIGH, MEDIUM, LOW = "high", "medium", "low"
_WEIGHT = {HIGH: 10.0, MEDIUM: 3.0, LOW: 0.5}


@dataclass(frozen=True)
class Finding:
    tool: str  # "ruff", "secrets", "patterns", "complexity"
    rule: str
    severity: str
    path: str
    line: int
    message: str


@dataclass(frozen=True)
class FunctionMetric:
    path: str
    name: str
    start_line: int
    end_line: int
    complexity: int  # 1 + decision points
    nesting: int  # deepest block nesting inside it

    @property
    def lines(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class Analysis:
    files: int = 0
    lines: int = 0
    code_lines: int = 0  # in programming languages: what the score is per
    languages: dict[str, int] = field(default_factory=dict)  # language -> lines
    findings: list[Finding] = field(default_factory=list)
    functions: list[FunctionMetric] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counted = {HIGH: 0, MEDIUM: 0, LOW: 0}
        for finding in self.findings:
            counted[finding.severity] += 1
        return counted

    @property
    def score(self) -> int:
        """100 for clean code, less for each finding (a high one weighs 20 low ones),
        per thousand lines, so a large codebase is not punished for its size."""
        weight = sum(_WEIGHT[f.severity] for f in self.findings)
        density = weight / max((self.code_lines or self.lines) / 1000, 0.5)
        return max(0, min(100, round(100 - 2.5 * density)))

    @property
    def grade(self) -> str:
        return grade_of(self.score)


def grade_of(score: int) -> str:
    for floor, grade in ((90, "A"), (80, "B"), (65, "C"), (50, "D")):
        if score >= floor:
            return grade
    return "F"


# --- Languages ---------------------------------------------------------------------------

_LANGUAGES = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "tsx",
    ".go": "go",
}
# Other files worth a secrets scan and a size count.
TEXT_SUFFIXES = frozenset(
    {
        *_LANGUAGES,
        ".java", ".kt", ".rb", ".php", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift",
        ".scala", ".sh", ".bash", ".sql", ".yml", ".yaml", ".toml", ".json", ".ini", ".cfg",
        ".env", ".properties", ".tf", ".md", ".txt", ".html", ".css", ".vue", ".svelte",
    }
)  # fmt: skip


# Programming languages (the rest is configuration, documentation and data).
CODE_SUFFIXES = frozenset(
    {*_LANGUAGES, ".java", ".kt", ".rb", ".php", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs",
     ".swift", ".scala", ".sh", ".bash", ".sql", ".vue", ".svelte"}
)  # fmt: skip
_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)|(^|/)test_[^/]+$|[._-](test|spec)\.\w+$"
)


def is_code(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in CODE_SUFFIXES


def is_test(path: str) -> bool:
    return bool(_TEST_PATH.search(path))


def for_tests(findings: list[Finding]) -> list[Finding]:
    """Findings in test code count as low: tests are not shipped, and security rules
    flag their fake passwords and temporary paths."""
    return [
        Finding(f.tool, f.rule, LOW, f.path, f.line, f.message)
        if f.severity != LOW and is_test(f.path) and f.tool != "secrets"
        else f
        for f in findings
    ]


def language_of(path: str) -> str | None:
    return _LANGUAGES.get(PurePosixPath(path).suffix.lower())


def family_of(path: str) -> str | None:
    """ "python", "typescript" (also JavaScript), "go" or None."""
    language = language_of(path)
    if language in ("typescript", "tsx", "javascript"):
        return "typescript"
    return language


# --- Ruff --------------------------------------------------------------------------------

# Bugs, security (Bandit's rules) and common mistakes; not style. Complexity is measured
# here, the same way for every language.
RUFF_RULES = "E9,E711,E712,E721,E722,F,B,S,PLE,PLW,BLE,ASYNC,DTZ,SIM,RET,ERA,ARG"
# Rules that are noise in a review: asserts (S101, fine in tests), random() (S311).
RUFF_IGNORE = "S101,S311,ERA001"


def _ruff_severity(code: str) -> str:
    if code.startswith(("E9", "F63", "F7", "F82", "PLE")) or (
        code[:1] == "S" and code[1:2].isdigit() and code not in ("S110", "S112")
    ):
        return HIGH
    if code.startswith(("B", "E722", "PLW", "BLE", "ASYNC", "DTZ", "F811", "F601")):
        return MEDIUM
    return LOW


def ruff(root: Path, timeout: float = 120.0) -> list[Finding]:
    """Ruff on every Python file under `root`, with its own settings, not the repo's."""
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--isolated",
        "--no-cache",
        "--exit-zero",
        "--output-format",
        "json",
        "--select",
        RUFF_RULES,
        "--ignore",
        RUFF_IGNORE,
        "--line-length",
        "120",
        str(root),
    ]
    try:
        # The command is fixed; only the folder (ours) varies.
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        raw = json.loads(done.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        logger.warning("ruff could not run: %s", error)
        return []
    findings = []
    for item in raw:
        code = item.get("code") or "E999"  # a file Ruff cannot parse has no code
        path = Path(item["filename"]).resolve().relative_to(root.resolve()).as_posix()
        findings.append(
            Finding(
                "ruff",
                code,
                _ruff_severity(code),
                path,
                (item.get("location") or {}).get("row", 1),
                item.get("message", ""),
            )
        )
    return findings


# --- Secrets -----------------------------------------------------------------------------

_SECRETS = [
    ("aws-access-key", HIGH, re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private-key", HIGH, re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY")),
    ("github-token", HIGH, re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_\w{40,})")),
    ("slack-token", HIGH, re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("google-api-key", HIGH, re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("ai-api-key", HIGH, re.compile(r"\bsk-(?:ant-|proj-|or-v1-)?[A-Za-z0-9_-]{24,}")),
    ("stripe-key", HIGH, re.compile(r"\b[rs]k_live_[0-9A-Za-z]{20,}")),
    (
        "jwt",
        MEDIUM,
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ),
    (
        "hard-coded-secret",
        MEDIUM,
        re.compile(
            r"""(?i)\b(?:api[_-]?key|secret|passw(?:or)?d|access[_-]?token|auth[_-]?token)\b"""
            r"""\s*[:=]\s*["']([^"'\s]{12,})["']"""
        ),
    ),
]
# Values that are obviously placeholders, not secrets.
_PLACEHOLDER = re.compile(r"(?i)x{4,}|your|example|changeme|dummy|placeholder|<|\$\{|\{\{|test")


def _mask(value: str) -> str:
    return value[:4] + "…" + value[-2:] if len(value) > 8 else "…"


def scan_secrets(path: str, text: str) -> list[Finding]:
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        if len(line) > 2000:
            continue
        for rule, severity, pattern in _SECRETS:
            match = pattern.search(line)
            if not match:
                continue
            value = match.group(match.lastindex or 0)
            if rule == "hard-coded-secret" and _PLACEHOLDER.search(value):
                continue
            findings.append(
                Finding(
                    "secrets",
                    rule,
                    severity,
                    path,
                    number,
                    f"Possible {rule.replace('-', ' ')} in the code ({_mask(value)}); "
                    "move it to configuration and revoke it if it was ever committed.",
                )
            )
            break
    return findings


# --- Risky patterns (JavaScript, TypeScript, Go) -----------------------------------------

_PATTERNS: dict[str, list[tuple[str, str, re.Pattern[str], str]]] = {
    "typescript": [
        ("no-eval", HIGH, re.compile(r"(?<![\w.])eval\s*\("), "eval() runs arbitrary code."),
        ("no-new-func", HIGH, re.compile(r"\bnew\s+Function\s*\("), "new Function() is eval."),
        (
            "no-inner-html",
            MEDIUM,
            re.compile(r"\.(?:inner|outer)HTML\s*\+?=|insertAdjacentHTML\s*\("),
            "Setting HTML from strings invites cross-site scripting.",
        ),
        (
            "no-dangerous-html",
            MEDIUM,
            re.compile(r"dangerouslySetInnerHTML"),
            "dangerouslySetInnerHTML needs sanitised input.",
        ),
        (
            "no-shell-exec",
            MEDIUM,
            re.compile(r"\b(?:exec|execSync)\s*\(\s*[`'\"].*(?:\$\{|\"\s*\+|'\s*\+)"),
            "A shell command built from strings can be injected into.",
        ),
        (
            "no-sql-concat",
            MEDIUM,
            re.compile(r"\b(?:query|execute|raw)\s*\(\s*`[^`]*\$\{"),
            "SQL built with a template string can be injected into; use parameters.",
        ),
        (
            "tls-off",
            HIGH,
            re.compile(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED"),
            "Certificate checks are turned off.",
        ),
        ("no-debugger", LOW, re.compile(r"(?<![\w.])debugger\s*;"), "A debugger statement."),
        ("no-explicit-any", LOW, re.compile(r":\s*any\b(?!\w)"), "`any` turns type checks off."),
        ("loose-equality", LOW, re.compile(r"[^=!<>]==[^=]|!=[^=]"), "== coerces types; use ===."),
    ],
    "go": [
        (
            "tls-off",
            HIGH,
            re.compile(r"InsecureSkipVerify\s*:\s*true"),
            "Certificate checks are turned off.",
        ),
        (
            "shell-exec",
            MEDIUM,
            re.compile(r"exec\.Command\(\s*\"(?:sh|bash|cmd)\""),
            "A command run through a shell can be injected into.",
        ),
        (
            "sql-sprintf",
            MEDIUM,
            re.compile(r"\.(?:Query|Exec|QueryRow)\w*\(\s*fmt\.Sprintf"),
            "SQL built with Sprintf can be injected into; use parameters.",
        ),
        (
            "ignored-error",
            LOW,
            re.compile(r"^\s*_\s*(?:,\s*_\s*)?=\s*\w[\w.]*\("),
            "An error is discarded.",
        ),
    ],
}
_TODO = re.compile(r"\b(?:TODO|FIXME|XXX|HACK)\b")


def scan_patterns(path: str, text: str) -> list[Finding]:
    rules = _PATTERNS.get(family_of(path) or "", [])
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        if len(line) > 2000:
            continue
        stripped = line.lstrip()
        comment = stripped.startswith(("//", "#", "*", "/*"))
        if _TODO.search(line):
            findings.append(
                Finding("patterns", "todo", LOW, path, number, stripped[:160] or "TODO")
            )
        if comment:
            continue
        for rule, severity, pattern, message in rules:
            if pattern.search(line):
                findings.append(Finding("patterns", rule, severity, path, number, message))
    return findings


# --- Complexity, from the syntax tree ----------------------------------------------------

_FUNCTIONS = {
    "python": {"function_definition"},
    "typescript": {
        "function_declaration",
        "function_expression",
        "function",
        "generator_function_declaration",
        "method_definition",
        "arrow_function",
    },
    "go": {"function_declaration", "method_declaration", "func_literal"},
}
_DECISIONS = {
    "python": {
        "if_statement", "elif_clause", "for_statement", "while_statement", "except_clause",
        "conditional_expression", "case_clause", "for_in_clause", "if_clause", "assert_statement",
    },
    "typescript": {
        "if_statement", "for_statement", "for_in_statement", "while_statement", "do_statement",
        "switch_case", "catch_clause", "ternary_expression",
    },
    "go": {
        "if_statement", "for_statement", "expression_case", "type_case", "communication_case",
    },
}  # fmt: skip
_BLOCKS = {
    "python": {"if_statement", "for_statement", "while_statement", "try_statement",
               "with_statement", "match_statement"},
    "typescript": {"if_statement", "for_statement", "for_in_statement", "while_statement",
                   "do_statement", "try_statement", "switch_statement"},
    "go": {"if_statement", "for_statement", "expression_switch_statement",
           "type_switch_statement", "select_statement"},
}  # fmt: skip
_BOOLEAN = {"&&", "||", "??", "and", "or"}


@cache
def _parser(language: str):
    from tree_sitter import Language, Parser

    if language == "python":
        import tree_sitter_python as grammar

        return Parser(Language(grammar.language()))
    if language == "go":
        import tree_sitter_go as grammar

        return Parser(Language(grammar.language()))
    import tree_sitter_typescript as grammar

    tsx = language == "tsx"
    return Parser(Language(grammar.language_tsx() if tsx else grammar.language_typescript()))


def _name(node, source: bytes, family: str) -> str:
    named = node.child_by_field_name("name")
    if named is not None:
        return source[named.start_byte : named.end_byte].decode("utf-8", "replace")
    parent = node.parent
    # `const handler = () => …` and `x.y = function () {…}`: the name being assigned.
    if family == "typescript" and parent is not None and parent.type == "variable_declarator":
        target = parent.child_by_field_name("name")
        if target is not None:
            return source[target.start_byte : target.end_byte].decode("utf-8", "replace")
    return "<anonymous>"


def measure(path: str, text: str) -> list[FunctionMetric]:
    """Each function's complexity and nesting. Anonymous functions of three lines or
    fewer (callbacks) are skipped."""
    language = language_of(path)
    family = family_of(path)
    if language is None or family is None:
        return []
    language = "typescript" if language == "javascript" else language
    source = text.encode("utf-8", "replace")
    try:
        tree = _parser(language).parse(source)
    except (ValueError, RuntimeError):
        return []
    functions, decisions, blocks = _FUNCTIONS[family], _DECISIONS[family], _BLOCKS[family]
    metrics: list[FunctionMetric] = []

    def visit(node, owner: list | None, depth: int, prefix: str) -> None:
        # owner: [complexity, deepest] of the function being measured.
        if node.type in functions:
            name = _name(node, source, family)
            qualified = f"{prefix}{name}" if name != "<anonymous>" else name
            state = [1, 0]
            for child in node.children:
                visit(child, state, 0, f"{qualified}.")
            start, end = node.start_point[0] + 1, node.end_point[0] + 1
            if name != "<anonymous>" or end - start >= 3:
                metrics.append(FunctionMetric(path, qualified, start, end, state[0], state[1]))
            return
        if node.type in ("class_definition", "class_declaration", "class"):
            named = node.child_by_field_name("name")
            label = source[named.start_byte : named.end_byte].decode() if named else "<class>"
            for child in node.children:
                visit(child, owner, depth, f"{prefix}{label}.")
            return
        if owner is not None:
            if node.type in decisions:
                owner[0] += 1
            elif node.type in ("binary_expression", "boolean_operator"):
                operator = node.child_by_field_name("operator")
                if operator is not None and operator.type in _BOOLEAN:
                    owner[0] += 1
            if node.type in blocks:
                depth += 1
                owner[1] = max(owner[1], depth)
        for child in node.children:
            visit(child, owner, depth, prefix)

    try:
        visit(tree.root_node, None, 0, "")
    except RecursionError:  # pathologically deep code (generated files)
        return metrics
    return metrics


COMPLEX = 15  # McCabe's "complex"; above this a function is reported
VERY_COMPLEX = 30
DEEP = 5


def complexity_findings(metrics: Iterable[FunctionMetric]) -> list[Finding]:
    findings = []
    for m in metrics:
        if m.complexity > COMPLEX:
            severity = MEDIUM if m.complexity <= VERY_COMPLEX else HIGH
            findings.append(
                Finding(
                    "complexity",
                    "too-complex",
                    severity,
                    m.path,
                    m.start_line,
                    f"{m.name} has cyclomatic complexity {m.complexity} over {m.lines} lines; "
                    "split it into smaller functions.",
                )
            )
        elif m.nesting > DEEP:
            findings.append(
                Finding(
                    "complexity",
                    "too-deep",
                    MEDIUM,
                    m.path,
                    m.start_line,
                    f"{m.name} nests {m.nesting} blocks deep; return early or extract helpers.",
                )
            )
    return findings


# --- Putting it together -----------------------------------------------------------------


def analyse_files(files: Mapping[str, str], *, run_ruff: bool = True) -> Analysis:
    """Every check on in-memory files ({relative path: text})."""
    analysis = Analysis()
    python: dict[str, str] = {}
    for path, text in files.items():
        lines = text.count("\n") + 1
        analysis.files += 1
        analysis.lines += lines
        if is_code(path):
            analysis.code_lines += lines
        language = family_of(path) or (PurePosixPath(path).suffix.lstrip(".") or "text")
        analysis.languages[language] = analysis.languages.get(language, 0) + lines
        analysis.findings += scan_secrets(path, text)
        analysis.findings += scan_patterns(path, text)
        metrics = measure(path, text)
        analysis.functions += metrics
        analysis.findings += complexity_findings(metrics)
        if family_of(path) == "python":
            python[path] = text
    if python and run_ruff:
        with tempfile.TemporaryDirectory(prefix="atlas-review-") as folder:
            root = Path(folder)
            for path, text in python.items():
                target = root / PurePosixPath(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            analysis.findings += ruff(root)
    analysis.findings = for_tests(analysis.findings)
    analysis.findings.sort(key=lambda f: (-_WEIGHT[f.severity], f.path, f.line))
    return analysis
