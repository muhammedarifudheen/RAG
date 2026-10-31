"""Before answering, the user's goal: the literal question, the goal, the constraints."""

from types import SimpleNamespace

from app.assistant.service import Assistant, Options

REPLY = (
    "Literal question: how do I sign a cookie?\n"
    "Underlying goal: keep a session cookie from being tampered with\n"
    "Implied constraints: no hand-rolled crypto, works with Flask\n"
    "Reframe: answering how to protect a session cookie, not just sign a string\n"
    "---\n"
    "Use a signed serializer for the cookie value."
)


class Agent:
    def __init__(self, reply):
        self.name, self.label, self.models = "gemini", "Gemini", ["g1"]
        self.reply, self.calls = reply, []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system))
        outcome.model = model
        for start in range(0, len(self.reply), 9):
            yield self.reply[start : start + 9]


def test_the_goal_is_reconstructed_folded_away_and_the_reframe_kept():
    agent = Agent(REPLY)
    events = list(
        Assistant([agent]).respond(
            "how do I sign a cookie?", [], (), "auto", Options(instructions="Be brief.")
        )
    )
    system = agent.calls[0].system
    assert "Before answering, reconstruct what the user is actually trying to achieve:" in system
    assert system.endswith("Be brief.")  # the user's standing instructions stay last
    streamed = "".join(data["text"] for name, data in events if name == "delta")
    assert streamed.startswith("Use a signed serializer")
    done = events[-1][1]
    assert done["answer"] == "Use a signed serializer for the cookie value."
    assert done["intent"] == {
        "literal": "how do I sign a cookie?",
        "goal": "keep a session cookie from being tampered with",
        "constraints": "no hand-rolled crypto, works with Flask",
        "reframe": "answering how to protect a session cookie, not just sign a string",
    }


def test_small_talk_is_not_reconstructed():
    agent = Agent("Hello!")
    done = list(Assistant([agent]).respond("hi", [], (), "auto", Options()))[-1][1]
    assert "reconstruct what the user" not in agent.calls[0].system
    assert done["intent"] is None
