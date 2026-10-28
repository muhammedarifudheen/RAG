"""The code analyser: its checks, a whole repository's report, and code reviews in chat."""

import contextlib
import threading
from pathlib import Path
from types import SimpleNamespace

from app.analysis.repo import analyse_tree, summary_for_agents
from app.analysis.review import code_files, files_summary, repo_url, to_schema, wants_review
from app.analysis.static import (
    HIGH,
    LOW,
    MEDIUM,
    analyse_files,
    measure,
    scan_patterns,
    scan_secrets,
)
from app.assistant import service as service_module
from app.assistant.images import GeminiImages, HordeImages, ImageError, TogetherImages
from app.assistant.service import Assistant, Options
from app.schemas import Attachment

BAD_PYTHON = """import os
import subprocess

API_KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"


def run(cmd, items=[]):
    try:
        subprocess.call(cmd, shell=True)
    except:
        pass
    return eval(cmd)


def missing():
    return undefined_name
"""

BAD_TS = """export function render(el: any, html: string) {
  el.innerHTML = html;
  if (html == "x") { debugger; }
  db.query(`SELECT * FROM t WHERE id = ${html}`);
  return eval(html);
}
"""


def rules(findings):
    return {(f.path, f.rule): f for f in findings}


# --- The checks --------------------------------------------------------------------------


def test_python_bugs_and_security_problems_are_found_by_ruff():
    found = rules(analyse_files({"app.py": BAD_PYTHON}).findings)
    assert found[("app.py", "S602")].severity == HIGH  # shell=True
    assert found[("app.py", "S307")].severity == HIGH  # eval
    assert found[("app.py", "F821")].severity == HIGH  # undefined name
    assert found[("app.py", "B006")].severity == MEDIUM  # mutable default
    assert found[("app.py", "E722")].severity == MEDIUM  # bare except
    assert found[("app.py", "F401")].severity == LOW  # unused import
    assert found[("app.py", "F821")].line == 16


def test_a_leaked_key_is_found_and_masked():
    [finding] = scan_secrets("config.py", 'KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"\n')
    assert finding.rule == "ai-api-key" and finding.severity == HIGH and finding.line == 1
    assert "abcdefghijklmnop" not in finding.message


def test_placeholders_are_not_secrets():
    text = 'password = "your-password-here"\napi_key = "${API_KEY}"\ntoken = "xxxxxxxxxxxxxxxx"\n'
    assert scan_secrets("settings.py", text) == []


def test_risky_javascript_and_typescript_is_found():
    found = rules(scan_patterns("web/render.ts", BAD_TS))
    assert found[("web/render.ts", "no-eval")].severity == HIGH
    assert found[("web/render.ts", "no-inner-html")].severity == MEDIUM
    assert found[("web/render.ts", "no-sql-concat")].severity == MEDIUM
    assert found[("web/render.ts", "no-explicit-any")].line == 1
    assert ("web/render.ts", "no-debugger") in found
    assert ("web/render.ts", "loose-equality") in found


def test_risky_go_is_found():
    code = "package main\nvar c = tls.Config{InsecureSkipVerify: true}\n"
    assert [f.rule for f in scan_patterns("main.go", code)] == ["tls-off"]


def test_complexity_and_nesting_are_measured_on_the_syntax_tree():
    code = """def tangled(a, b):
    for i in range(a):
        if i and b:
            while b:
                b -= 1
    return a if a else b


class Box:
    def size(self):
        return 1
"""
    metrics = {m.name: m for m in measure("x.py", code)}
    # for, if, `and`, while, conditional expression: 1 + 5
    assert metrics["tangled"].complexity == 6
    assert metrics["tangled"].nesting == 3
    assert metrics["Box.size"].complexity == 1
    assert (metrics["tangled"].start_line, metrics["tangled"].end_line) == (1, 6)


def test_typescript_and_go_functions_are_measured_and_named():
    ts = "const handler = (x: number) => {\n  if (x > 1 && x < 5) { return 1; }\n  return x ? 2 : 3;\n};\n"
    [metric] = measure("h.ts", ts)
    assert metric.name == "handler" and metric.complexity == 4
    go = "package main\nfunc f(x int) int {\n\tif x > 1 || x < 0 {\n\t\treturn 1\n\t}\n\treturn 0\n}\n"
    [metric] = measure("main.go", go)
    assert metric.name == "f" and metric.complexity == 3


def test_very_complex_functions_are_reported():
    branches = "\n".join(f"    if x == {n}:\n        return {n}" for n in range(20))
    code = f"def big(x):\n{branches}\n    return -1\n"
    [finding] = [f for f in analyse_files({"big.py": code}).findings if f.tool == "complexity"]
    assert finding.rule == "too-complex" and finding.severity == MEDIUM
    assert "complexity 21" in finding.message


def test_findings_in_tests_count_as_low():
    analysis = analyse_files({"tests/test_app.py": BAD_PYTHON})
    assert {f.severity for f in analysis.findings if f.tool == "ruff"} == {LOW}
    # A leaked key is a leaked key, even in a test.
    assert any(f.tool == "secrets" and f.severity == HIGH for f in analysis.findings)


def test_clean_code_scores_well_and_bad_code_badly():
    clean = analyse_files({"ok.py": "def add(a: int, b: int) -> int:\n    return a + b\n"})
    assert (clean.score, clean.grade, clean.counts) == (
        100,
        "A",
        {"high": 0, "medium": 0, "low": 0},
    )
    bad = analyse_files({"app.py": BAD_PYTHON})
    assert bad.score < 50 and bad.grade == "F"


# --- A whole repository ------------------------------------------------------------------


def write(root: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def test_a_repository_report_finds_cycles_hotspots_and_tests(tmp_path):
    write(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "from pkg import b\n\ndef fa():\n    return b.fb()\n",
            "pkg/b.py": "from pkg import a\n\ndef fb():\n    return eval('1')\n",
            "pkg/c.py": "from pkg import b\n",
            "tests/test_a.py": "from pkg import a\n\ndef test_fa():\n    assert a.fa()\n",
            "node_modules/lib/index.js": "eval('x')\n",
            "pnpm-lock.yaml": "lockfileVersion: 9\n" * 500,
            "dist/app.min.js": "var a=1;" * 2000,
        },
    )
    progress = []
    report = analyse_tree(tmp_path, progress.append)
    analysis = report.analysis
    paths = {f.path for f in analysis.findings}
    assert "node_modules/lib/index.js" not in paths  # other people's code
    assert analysis.files == 5  # no lock file, nothing vendored or built
    assert report.cycles == [["pkg/a.py", "pkg/b.py"]]
    assert dict(report.most_imported)["pkg/b.py"] == 2
    assert report.test_files == 1
    assert report.riskiest[0].path == "pkg/b.py"  # eval, and imported by two files
    assert any("fb" in where for where in report.excerpts)
    assert progress[-1] == "Linking imports"

    text = summary_for_agents(report)
    assert "pkg/a.py -> pkg/b.py" in text
    assert "S307" in text
    schema = to_schema(analysis, report)
    assert schema.cycles == [["pkg/a.py", "pkg/b.py"]]
    assert schema.riskiest[0].path == "pkg/b.py"


# --- Finding the code in a message -------------------------------------------------------


def test_code_comes_from_attachments_fences_and_github_file_links():
    fetched = []

    def fetch(url):
        fetched.append(url)
        return "print('hi')\n"

    question = (
        "Review this:\n```python\nx = 1\n```\nand\n```\nfunc main() {}\npackage main\n```\n"
        "and https://github.com/o/r/blob/main/src/app.py please"
    )
    files = code_files(
        question, [Attachment(kind="text", name="notes/util.ts", text="let a = 1")], fetch
    )
    assert files == {
        "notes/util.ts": "let a = 1",
        "snippet-1.py": "x = 1\n",
        "snippet-2.go": "func main() {}\npackage main\n",
        "src/app.py": "print('hi')\n",
    }
    assert fetched == ["https://raw.githubusercontent.com/o/r/main/src/app.py"]


def test_review_requests_need_code_or_a_repository():
    assert wants_review("Please review this code", True)
    assert wants_review("audit https://github.com/pallets/flask for security issues", False)
    assert not wants_review("Please review this code", False)
    assert not wants_review("What is a code review?", False)
    assert (
        repo_url("https://github.com/socketio/socket.io") == "https://github.com/socketio/socket.io"
    )
    assert (
        repo_url("analyse https://github.com/pallets/flask.") == "https://github.com/pallets/flask"
    )
    assert repo_url("see https://github.com/o/r/blob/main/x.py") is None


# --- Reviews in chat ---------------------------------------------------------------------


class Agent:
    def __init__(self, name, replies):
        self.name, self.label = name, name.title()
        self.replies = dict(replies)
        self.models = list(self.replies)
        self.calls = []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None):
        self.calls.append(SimpleNamespace(model=model, system=system, turns=turns))
        outcome.model = model
        yield self.replies[model]


class NoSearch:
    def search(self, query, recent=False):
        raise AssertionError("a code review does not search the web")


def test_pasted_code_is_analysed_and_the_agents_review_the_findings():
    gemini = Agent("gemini", {"g1": "**Verdict**: risky."})
    assistant = Assistant([gemini], web=NoSearch())
    question = f"Review this code:\n```python\n{BAD_PYTHON}```"
    events = list(assistant.respond(question, [], ()))
    names = [name for name, _ in events]
    assert names[:3] == ["analysing", "analysis", "route"]
    analysis = events[1][1]
    assert analysis["counts"]["high"] >= 3
    assert any(f["rule"] == "S602" for f in analysis["findings"])
    assert events[2][1]["route"] == "review"
    call = gemini.calls[0]
    assert "This is a code review" in call.system
    assert "<static_analysis>" in call.turns[-1].content
    assert "S602" in call.turns[-1].content
    done = events[-1][1]
    assert done["analysis"]["grade"] == "F"
    assert done["answer"] == "**Verdict**: risky."


def test_the_review_task_reviews_an_attached_file_without_asking_for_it_in_words():
    gemini = Agent("gemini", {"g1": "Fine."})
    assistant = Assistant([gemini])
    options = Options(
        task="review", attachments=[Attachment(kind="text", name="ok.py", text="x = 1\n")]
    )
    events = list(assistant.respond("thoughts?", [], (), "auto", options))
    assert events[-1][1]["analysis"]["files"] == 1
    assert events[-1][1]["route"] == "review"


def test_a_repository_link_is_cloned_analysed_and_reviewed(tmp_path):
    write(tmp_path, {"app.py": "def f():\n    return eval('1')\n"})

    def analyse_repo(url, progress):
        progress("Cloning the repository")
        report = analyse_tree(tmp_path, progress)
        report.repo, report.commit = url, "abc123"
        return report

    gemini = Agent("gemini", {"g1": "Review."})
    assistant = Assistant([gemini], analyse_repo=analyse_repo)
    events = list(assistant.respond("Audit https://github.com/o/r for bugs", [], ()))
    messages = [data["message"] for name, data in events if name == "analysing"]
    assert messages[:2] == ["Analysing https://github.com/o/r", "Cloning the repository"]
    assert "<repository_analysis" in gemini.calls[0].turns[-1].content
    done = events[-1][1]
    assert done["analysis"]["repo"] == "https://github.com/o/r"
    assert done["analysis"]["commit"] == "abc123"


def test_a_repository_that_cannot_be_analysed_ends_with_a_clear_error():
    def analyse_repo(url, progress):
        raise RuntimeError("not found")

    assistant = Assistant([Agent("gemini", {"g1": "x"})], analyse_repo=analyse_repo)
    events = list(assistant.respond("review https://github.com/o/missing", [], ()))
    name, data = events[-1]
    assert name == "error" and data["status"] == 422
    assert "public GitHub repository" in data["detail"]


def test_one_repository_is_analysed_at_a_time():
    started, release = threading.Event(), threading.Event()

    def slow(url, progress):
        started.set()
        release.wait(5)
        raise RuntimeError("stop")

    first = Assistant([Agent("gemini", {"g1": "x"})], analyse_repo=slow)
    events = first.respond("review https://github.com/o/one", [], ())
    next(events)  # the analysis is running
    started.wait(5)
    second = Assistant([Agent("gemini", {"g1": "x"})], analyse_repo=slow)
    name, data = list(second.respond("review https://github.com/o/two", [], ()))[-1]
    assert name == "error" and data["status"] == 409
    release.set()
    list(events)
    assert not service_module._REPO_ANALYSIS.locked()


def test_the_findings_summary_says_when_nothing_was_found():
    text = files_summary(analyse_files({"ok.py": "x = 1\n"}))
    assert "found nothing" in text


# --- More picture agents -----------------------------------------------------------------


class Posting:
    def __init__(self, reply, status=200):
        self.reply, self.status, self.sent = reply, status, []

    def post(self, url, headers=None, json=None):
        self.sent.append((url, headers, json))
        return SimpleNamespace(status_code=self.status, json=lambda: self.reply)


def test_together_draws_with_its_free_flux_model():
    http = Posting({"data": [{"b64_json": "AAAA"}]})
    url = TogetherImages(http, "t", "black-forest-labs/FLUX.1-schnell-Free").draw("a fox", 3)
    assert url == "data:image/jpeg;base64,AAAA"
    assert http.sent[0][2]["model"] == "black-forest-labs/FLUX.1-schnell-Free"


def test_gemini_returns_its_picture_inline():
    reply = {
        "candidates": [
            {"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "QQ=="}}]}}
        ]
    }
    http = Posting(reply)
    assert (
        GeminiImages(http, "g", "gemini-2.5-flash-image").draw("a fox", 3)
        == "data:image/png;base64,QQ=="
    )
    assert http.sent[0][2]["generationConfig"]["responseModalities"] == ["IMAGE"]


def test_each_horde_model_is_its_own_agent_with_a_negative_prompt_and_its_size():
    class Stub:
        def __init__(self):
            self.json = None

        def post(self, url, headers, json):
            self.json = json
            return SimpleNamespace(status_code=500, json=dict)

    http = Stub()
    painter = HordeImages(http, "k", ["Juggernaut XL"], label="AI Horde · Juggernaut XL")
    assert painter.label == "AI Horde · Juggernaut XL"
    with contextlib.suppress(ImageError):  # the stub refuses; the request is what matters
        painter.draw("a fox", 1)
    assert http.json["prompt"].startswith("a fox ### blurry")
    assert http.json["params"]["width"] == 1024
    small = Stub()
    with contextlib.suppress(ImageError):
        HordeImages(small, "k", ["Deliberate"]).draw("a fox", 1)
    assert small.json["params"]["width"] == 512
