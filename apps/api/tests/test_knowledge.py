"""The knowledge base improving itself: the answer log, wanted sources, refreshes, the note."""

import uuid

from seed import FakeEmbedder

from app.services.knowledge import (
    export_log,
    health_note,
    import_log,
    knowledge_health,
    log_answer,
    note_suggestion,
)


def answer(question, state, files=(), verified=0, citations=0, score=0.6):
    return {
        "question": question,
        "epistemic": state,
        "route": "sources",
        "chunks": [{"file": f, "score": score} for f in files],
        "citations": [{"verified": i < verified} for i in range(citations)],
        "confidence": {"level": "high"} if verified else None,
    }


def test_the_note_reads_like_the_users_three_parts():
    note = health_note(
        {
            "gaps": [{"question": "How do Flask sessions work?", "times": 3}],
            "sources": [
                {"action": "add", "source": "https://github.com/pallets/flask", "why": "x"}
            ],
            "well_answered": {"question": "What does format_name return?", "score": 0.41},
        }
    )
    assert "Top recurring gaps:\n- How do Flask sessions work? (3×)" in note
    assert "- Add https://github.com/pallets/flask: x" in note
    assert "Answered surprisingly well:\n- What does format_name return?" in note
    assert "- none yet" in health_note({"gaps": [], "sources": [], "well_answered": None})


def test_answers_are_logged_and_a_topic_short_three_times_is_wanted(db):
    embedder, chat = FakeEmbedder(), uuid.uuid4().hex
    topic = f"How does the {uuid.uuid4().hex[:8]} cache expire?"
    for _ in range(3):
        log_answer(db, embedder, answer(topic, "absent"), chat)
    log_answer(
        db,
        embedder,
        answer("What does format_name return?", "known", ["pkg/models.py"], 2, 2, 0.31),
        chat,
    )

    health = knowledge_health(db, chat)
    assert health["scope"] == "chat" and health["answers"] == 4
    assert health["gaps"][0] == {"question": topic, "times": 3}
    assert health["well_answered"]["question"] == "What does format_name return?"
    overall = knowledge_health(db)
    assert any(g["question"] == topic and g["times"] >= 3 for g in overall["gaps"])


def test_the_gap_finders_suggestion_becomes_a_source_to_add(db):
    embedder, chat = FakeEmbedder(), uuid.uuid4().hex
    question = f"What is {uuid.uuid4().hex[:8]}?"
    log_answer(db, embedder, answer(question, "absent"), chat)
    note_suggestion(db, question, chat, "https://example.org/docs")
    sources = knowledge_health(db, chat)["sources"]
    assert {
        "action": "add",
        "source": "https://example.org/docs",
        "why": "Suggested for 1 gap(s)",
    } in sources


def test_disagreeing_sources_propose_refreshing_the_older(db):
    embedder = FakeEmbedder()
    # pkg/models.py (acme/pkg) and the Alan Turing article: two sources on one answer.
    log_answer(
        db,
        embedder,
        answer("Who is right?", "conflicted", ["pkg/models.py", "wikipedia/en/Alan_Turing"]),
        None,
    )
    refresh = [s for s in knowledge_health(db)["sources"] if s["action"] == "refresh"]
    assert refresh and refresh[0]["why"].startswith("Disagrees with")


def test_the_log_is_exported_and_only_restored_into_an_empty_one(db):
    embedder = FakeEmbedder()
    log_answer(db, embedder, answer("Exported?", "known"), "x")
    exported = export_log(db)
    assert any(a["question"] == "Exported?" for a in exported["answers"])
    assert import_log(db, embedder, exported) == 0  # the log is not empty


def test_ask_logs_answers_and_returns_a_chats_note(client):
    from app.assistant import get_assistant
    from app.assistant.service import Assistant
    from app.main import app

    class Agent:
        name, label, models = "gemini", "Gemini", ["g1"]

        def searches(self, model):
            return False

        def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
            outcome.model = model
            yield "It title-cases it [pkg/models.py:20-21]."

    chat = uuid.uuid4().hex
    app.dependency_overrides[get_assistant] = lambda: Assistant([Agent()])
    try:
        client.post(
            "/ask",
            json={"question": "format name of a user", "style": "concise"},
            headers={"X-Atlas-Chat": chat},
        )
        note = client.post(
            "/ask",
            json={"question": "knowledge health", "task": "health"},
            headers={"X-Atlas-Chat": chat},
        ).json()
    finally:
        app.dependency_overrides.pop(get_assistant, None)
    assert note["knowledge_health"]["scope"] == "chat"
    assert note["knowledge_health"]["answers"] == 1
    assert note["answer"].startswith("**Knowledge health**")
