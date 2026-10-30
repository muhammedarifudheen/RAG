"""Code questions over code excerpts are answered with the user's code-aware prompt."""

from types import SimpleNamespace

from app.assistant.router import wants_code_answer
from app.assistant.service import Assistant, Options
from app.schemas import CodeChunk


def chunk(language="python", score=0.8):
    return CodeChunk(
        symbol_id=1,
        name="Signer.unsign",
        kind="method",
        file="itsdangerous/signer.py",
        language=language,
        start_line=244,
        end_line=254,
        signature="def unsign(self, signed_value)",
        score=score,
        snippet="def unsign(self, signed_value):\n    return self.verify_signature(value, sig)",
        snippet_end_line=245,
        truncated=False,
        citation="[itsdangerous/signer.py:244-245]",
    )


class Agent:
    def __init__(self):
        self.name, self.label, self.models = "gemini", "Gemini", ["g1"]
        self.calls = []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system, content=turns[-1].content))
        outcome.model = model
        yield "It calls verify_signature [itsdangerous/signer.py:244-245]."


def test_which_questions_are_about_code():
    assert wants_code_answer("explain this", "code", ["markdown"])
    assert wants_code_answer("who calls unsign()?", "sources", ["markdown"])
    assert wants_code_answer("how are values signed?", "sources", ["python", "python", "markdown"])
    assert not wants_code_answer("what does the guide say?", "sources", ["markdown", "markdown"])
    assert not wants_code_answer("who calls unsign()?", "general", ["python"])
    assert not wants_code_answer("who calls unsign()?", "code", [])


def test_a_code_question_gets_the_code_aware_prompt_with_its_context():
    agent = Agent()
    list(
        Assistant([agent]).respond("Who calls verify_signature?", [chunk()], (), "auto", Options())
    )
    message = agent.calls[0].content
    assert message.startswith("You are a codebase assistant.\nWhen answering questions about code:")
    assert (
        "Context:\n[itsdangerous/signer.py:244-245]\n244| def unsign(self, signed_value):"
        in message
    )
    assert message.endswith("Question: Who calls verify_signature?")


def test_prose_excerpts_and_strict_answers_keep_their_own_prompts():
    agent = Agent()
    list(
        Assistant([agent]).respond(
            "What does the guide say?", [chunk("markdown")], (), "auto", Options()
        )
    )
    assert "<excerpt" in agent.calls[0].content
    strict = Agent()
    list(
        Assistant([strict]).respond(
            "Who calls unsign()?", [chunk()], (), "auto", Options(strict=True)
        )
    )
    assert strict.calls[0].content.startswith("Answer the question using ONLY the context below.")
