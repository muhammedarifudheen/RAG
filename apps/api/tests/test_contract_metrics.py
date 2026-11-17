"""dead_end_rate and unsupported_claim_rate: the gates that keep "never refuse" from becoming
"always make something up". The last tests run the whole harness against a fake server."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assistant.service import Assistant, Options
from app.schemas import CodeChunk
from evals import contract_metrics as cm
from evals.run_evals import contract_verdict, main

REPORT = (
    "**Evidence gap.** Nothing I could find answers this, and I will not guess.\n\n"
    "**Tools tried**\n- Knowledge base: vector and keyword search, 4 queries.\n"
    "- Web search: not used (this server answers from its knowledge base only).\n\n"
    "**Closest match**\n[a/signer.py:10-20] (similarity 0.20, below the relevance floor (0.30))\n"
    "> def unsign(self, value):\n\n"
    "**Next step**\n1. Rephrase with the exact name you expect to find.\n"
    "2. Add a source that covers this: paste a link on the Ingest page."
)
GAP = {"tools_tried": ["Knowledge base: 4 queries."], "closest": None, "next_steps": ["Rephrase."]}
CITED = {
    "answer": "Signer.unsign splits the value from its signature at the separator [a/signer.py:10-20].",
    "answer_state": "VERIFIED",
    "citations": [
        {
            "ref": "[a/signer.py:10-20]",
            "file": "a/signer.py",
            "start_line": 10,
            "end_line": 20,
            "verified": True,
        }
    ],
}


# --- dead ends --------------------------------------------------------------------------------


def test_bare_refusals_are_dead_ends():
    assert cm.is_dead_end({"answer": ""})
    assert cm.is_dead_end({"answer": "I don't have that in the knowledge base."})
    assert cm.is_dead_end({"answer": "I don't know.", "answer_state": "UNVERIFIED"})
    assert cm.is_dead_end({"answer": "Sorry, I cannot answer that.", "answer_state": None})
    # an evidence gap without its report is still a refusal
    assert cm.is_dead_end({"answer": "Nothing found.", "answer_state": "EVIDENCE_GAP"})
    assert cm.is_dead_end(
        {"answer": REPORT, "answer_state": "EVIDENCE_GAP", "evidence_gap": {"tools_tried": []}}
    )


def test_a_full_evidence_gap_and_a_real_answer_are_not():
    assert not cm.is_dead_end({"answer": REPORT, "answer_state": "EVIDENCE_GAP", "evidence_gap": GAP})
    assert not cm.is_dead_end({"answer": REPORT, "answer_state": "EVIDENCE_GAP"})  # older server
    assert not cm.is_dead_end(CITED)
    # a refusal-sounding sentence inside a long, cited answer is not a dead end
    long = "I don't know the default for older releases, but signing uses sha1 [a/signer.py:10-20]."
    assert not cm.is_dead_end({"answer": long + " More detail follows here.", "answer_state": "VERIFIED"})


# --- claims -----------------------------------------------------------------------------------


def test_claims_are_assertions_not_headings_questions_quotes_or_notes():
    answer = (
        "**TL;DR:** The signer verifies the signature in constant time [a/signer.py:10-20].\n\n"
        "### Call chain\n"
        "Is this what you meant to ask about?\n"
        "> def unsign(self, value): return value  # a quoted passage\n"
        "**Unverified:** this comes from the model's own knowledge, with no source to check it.\n"
        "```python\nsigner.unsign(value)\n```\n"
        "It then raises BadSignature when the two signatures differ at all.\n"
        "- Short bullet.\n"
    )
    claims = cm.extract_claims(answer)
    assert len(claims) == 2
    assert claims[0].startswith("The signer verifies") and claims[1].startswith("It then raises")


def test_a_cited_claim_needs_a_verified_citation():
    cites = [{"ref": "[a/signer.py:10-20]", "verified": True}]
    assert cm.score_claims(CITED["answer"], "VERIFIED", cites) == (1, 0)
    # the same sentence citing lines the server did not verify is unsupported
    unchecked = [{"ref": "[a/signer.py:10-20]", "verified": False}]
    assert cm.score_claims(CITED["answer"], "VERIFIED", unchecked) == (1, 1)
    # and with no citation at all
    plain = "Signer.unsign splits the value from its signature at the separator."
    assert cm.score_claims(plain, "VERIFIED", cites) == (1, 1)


def test_citations_match_across_dash_styles_and_backticks():
    cites = [{"ref": "[a/signer.py:10-20]", "verified": True}]
    for form in ("[a/signer.py:10–20]", "`a/signer.py:10-20`", "[a/signer.py:10 - 20]"):
        text = f"Signer.unsign splits the value from its signature at the separator {form}."
        assert cm.score_claims(text, "VERIFIED", cites) == (1, 0), form


def test_a_labelled_answer_is_honest_about_what_it_rests_on():
    unverified = (
        "**Unverified:** this comes from the model's own knowledge, with no source to check it "
        "against.\n\nCanberra is the capital city of Australia and it sits inland."
    )
    assert cm.score_claims(unverified, "UNVERIFIED", []) == (1, 0)
    assert cm.score_claims("Canberra is the capital city of Australia and it sits inland.",
                           "UNVERIFIED", []) == (1, 1)  # the label is missing
    reported = "Python 3.15 was released with new syntax features.\n\nReported (as of 2026-11-17): https://python.org/news"
    assert cm.score_claims(reported, "REPORTED", []) == (1, 0)


def test_an_inference_needs_its_label_and_something_cited_to_infer_from():
    note = "**Inference:** no source states this directly; it is derived from the evidence below.\n\n"
    body = "Changing the digest method would invalidate every token signed before the change."
    cites = [{"ref": "[a/signer.py:10-20]", "verified": True}]
    assert cm.score_claims(note + body, "INFERRED", cites) == (1, 0)
    assert cm.score_claims(note + body, "INFERRED", []) == (1, 1)  # nothing to infer from
    assert cm.score_claims(body, "INFERRED", cites) == (1, 1)  # unlabelled


def test_nothing_can_back_a_claim_about_a_question_the_sources_cannot_answer():
    # A confident, cited answer to an out-of-corpus question is the fabrication the gate exists for.
    assert cm.score_claims(CITED["answer"], "VERIFIED", CITED["citations"], answerable=False) == (1, 1)
    # An evidence gap makes no claims at all.
    assert cm.score_claims(REPORT, "EVIDENCE_GAP", [], answerable=False) == (0, 0)


def test_the_rates_and_the_verdict():
    rows = [
        {"dead_end": False, "claims": 4, "unsupported_claims": 0},
        {"dead_end": False, "claims": 0, "unsupported_claims": 0},
        {"dead_end": True, "claims": 0, "unsupported_claims": 0},
        {"dead_end": False, "claims": 4, "unsupported_claims": 1},
    ]
    summary = cm.summarise(rows)
    assert summary["dead_end_rate"] == 0.25 and summary["unsupported_claim_rate"] == 1 / 8
    clean = {"dead_end_rate": 0.0, "unsupported_claim_rate": 0.0, "claims_judged": 30}
    assert contract_verdict(clean) == []
    fabricating = contract_verdict({**clean, "unsupported_claim_rate": 0.1})
    assert any("fabricating" in line and "do not loosen the contract" in line for line in fabricating)
    refusing = contract_verdict({**clean, "dead_end_rate": 0.1})
    assert refusing and not any("fabricating" in line for line in refusing)
    assert contract_verdict({**clean, "claims_judged": 0})  # a 0 over nothing proves nothing


# --- through the assistant: a refusing model and a fabricating one -----------------------------


def chunk(score=0.8):
    return CodeChunk(
        symbol_id=1, name="Signer.unsign", kind="method", file="a/signer.py", language="python",
        start_line=10, end_line=20, signature=None, score=score,
        snippet="def unsign(self, value):\n    return value", snippet_end_line=20,
        truncated=False, citation="[a/signer.py:10-20]",
    )


class Agent:
    def __init__(self, *replies):
        self.name, self.label, self.models = "gemini", "Gemini", ["g1"]
        self.replies, self.calls = list(replies), []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system))
        outcome.model = model
        yield self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


def respond(agent, chunks, **options):
    events = list(Assistant([agent]).respond("q?", chunks, (), "auto", Options(**options)))
    return events[-1][1]


OUT_OF_CORPUS = {"id": "OOC", "answerable": False, "relevant": []}


def test_a_model_that_refuses_ends_in_a_report_that_passes_both_gates():
    data = respond(Agent("I don't have that in the knowledge base."), [chunk(0.1)], strict=True)
    row = cm.evaluate_response(OUT_OF_CORPUS, data)
    assert row["answer_state"] == "EVIDENCE_GAP"
    assert row["dead_end"] is False and row["unsupported_claims"] == 0


def test_a_model_that_keeps_refusing_still_passes_both_gates():
    agent = Agent("Sorry. I don't have that in the knowledge base.")
    data = respond(agent, [chunk()], strict=True, closest=chunk(0.2))
    row = cm.evaluate_response(OUT_OF_CORPUS, data)
    assert row["dead_end"] is False and row["unsupported_claims"] == 0


def test_a_model_that_fabricates_to_avoid_refusing_is_caught():
    fabricated = "The Rust borrow checker enforces ownership rules at compile time [a/signer.py:10-20]."
    data = respond(Agent(fabricated), [chunk()], strict=True)
    row = cm.evaluate_response(OUT_OF_CORPUS, data)
    # No refusal, but a confident cited answer to a question nothing in the sources can answer.
    assert row["dead_end"] is False
    assert row["unsupported_claims"] > 0


def test_a_good_answer_to_an_answerable_question_passes():
    data = respond(Agent("Signer.unsign splits the value from its signature [a/signer.py:10-20]."),
                   [chunk()], strict=True)
    row = cm.evaluate_response({"id": "Q", "answerable": True}, data)
    assert row["answer_state"] == "VERIFIED"
    assert row["dead_end"] is False and row["claims"] == 1 and row["unsupported_claims"] == 0


# --- the whole harness against a fake server ---------------------------------------------------


def serve(behaviour):
    """A fake /ask: `behaviour(question) -> response dict`."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"citations": [], "chunks": [], **behaviour(body["question"])}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def questions(tmp_path):
    path = tmp_path / "q.jsonl"
    rows = [
        {"id": "IN-1", "question": "How is a signature verified?", "answerable": True,
         "relevant": ["a/signer.py"]},
        {"id": "IN-2", "question": "How are tokens timed?", "answerable": True,
         "relevant": ["a/signer.py"]},
        {"id": "OOC-1", "question": "How many calories are in a banana?", "answerable": False,
         "relevant": []},
        {"id": "OOC-2", "question": "What causes the northern lights?", "answerable": False,
         "relevant": []},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def run_gate(server, path):
    url = f"http://127.0.0.1:{server.server_address[1]}"
    code = main(["--api", url, "--mode", "ask", "--contract-gate", "--golden", str(path)])
    server.shutdown()
    return code


def answer_for(question, out_of_corpus):
    if out_of_corpus(question):
        return out_of_corpus
    return {**CITED, "chunks": [], "epistemic": "known"}


def test_the_gate_passes_a_server_that_answers_and_reports_gaps(tmp_path, capsys):
    def behaviour(question):
        if "calories" in question or "northern" in question:
            return {"answer": REPORT, "answer_state": "EVIDENCE_GAP", "evidence_gap": GAP}
        return CITED

    assert run_gate(serve(behaviour), questions(tmp_path)) == 0
    assert "CONTRACT GATE: PASS" in capsys.readouterr().out


def test_the_gate_fails_a_server_that_refuses(tmp_path, capsys):
    def behaviour(question):
        if "calories" in question or "northern" in question:
            return {"answer": "I don't know.", "answer_state": "UNVERIFIED"}
        return CITED

    assert run_gate(serve(behaviour), questions(tmp_path)) == 1
    out = capsys.readouterr().out
    assert "CONTRACT GATE: FAIL" in out and "dead_end_rate" in out and "a bare refusal" in out


def test_the_gate_fails_a_server_that_fabricates_and_says_why(tmp_path, capsys):
    def behaviour(question):  # never refuses: answers everything, citing what it has
        return CITED

    assert run_gate(serve(behaviour), questions(tmp_path)) == 1
    out = capsys.readouterr().out
    assert "unsupported_claim_rate" in out
    assert "fabricating to satisfy 'never refuse'" in out and "do not loosen the contract" in out
