"""Attachments, answer style, pictures and shared chats."""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from app.assistant import Assistant, Options
from app.assistant.prompt import conversation, system_prompt
from app.assistant.providers import (
    ClaudeProvider,
    GeminiProvider,
    Image,
    OpenAICompatibleProvider,
    Outcome,
    ProviderError,
    Turn,
)
from app.assistant.router import classify, provider_order, wants_image
from app.schemas import Attachment, ChatTurn

PNG = "iVBORw0KGgo="  # stands in for an image's base64


class Provider:
    """A stand-in service that records what it was asked, temperature included."""

    def __init__(self, name, replies, models=("m1",)):
        self.name = name
        self.label = name.title()
        self.models = list(models)
        self.replies = list(replies)
        self.calls = []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None):
        self.calls.append(
            SimpleNamespace(model=model, system=system, turns=turns, temperature=temperature)
        )
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        outcome.model = model
        yield from reply


def run(assistant, question, history=(), options=None, mode="auto"):
    return list(assistant.respond(question, [], history, mode, options))


TEMPLATE = "https://draw.example/{prompt}?seed={seed}"


# --- Pictures ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "picture"),
    [
        ("draw a fox in the snow", True),
        ("Generate an image of a lighthouse", True),
        ("create a logo for my cafe", True),
        ("Can you paint a sunset?", True),
        ("picture of Paris at night", True),
        ("what is an image file?", False),
        ("create a docker image for my app", False),
        ("make a list of fruits", False),
    ],
)
def test_requests_to_draw_are_recognised(question, picture):
    assert wants_image(question) is picture


def test_a_picture_is_drawn_from_a_prompt_a_model_writes():
    writer = Provider("groq", [["A red fox curled up in deep snow, dawn light"]])
    events = run(Assistant([writer], image_url_template=TEMPLATE), "draw a fox in the snow")

    assert events[0] == ("route", {"route": "image", "mode": "auto", "providers": ["groq"]})
    done = events[-1][1]
    [image] = done["images"]
    assert image["prompt"] == "A red fox curled up in deep snow, dawn light"
    assert unquote(image["url"]).startswith(
        "https://draw.example/A red fox curled up in deep snow, dawn light?seed="
    )
    assert done["answer"].startswith("Here's your picture")
    assert done["route"] == "image"
    assert all(s.startswith("Draw") for s in done["suggestions"])
    # The writer was told to write an image prompt, not to answer.
    assert "image generator" in writer.calls[0].system


def test_without_a_working_model_the_request_itself_is_drawn():
    broken = Provider("gemini", [ProviderError("quota")])
    done = run(Assistant([broken], image_url_template=TEMPLATE), "Draw me a picture of a fox")[-1][
        1
    ]
    # The request's own words are dropped, leaving what to draw.
    assert done["images"][0]["prompt"] == "a fox"
    assert done["provider"] == "Pollinations"


def test_after_each_services_first_models_fail_their_other_models_are_tried():
    gemini = Provider(
        "gemini",
        [ProviderError("quota"), ProviderError("quota"), ["From the third model."]],
        models=("g1", "g2", "g3"),
    )
    groq = Provider("groq", [ProviderError("quota")], models=("q1",))
    done = run(Assistant([gemini, groq], models_per_provider=2), "What is HMAC?")[-1][1]

    assert done["answer"] == "From the third model."
    # g1 and g2, then the other service, then the model held back.
    assert [c.model for c in gemini.calls] == ["g1", "g2", "g3"]
    assert [c.model for c in groq.calls] == ["q1"]


def test_a_short_change_to_a_picture_draws_again_but_a_question_about_it_does_not():
    history = [
        ChatTurn(role="user", content="draw a fox"),
        ChatTurn(role="assistant", content="Here's your picture, drawn from this description: …"),
    ]
    writer = Provider("groq", [["A blue fox"], ["Foxes live in burrows."]])
    assistant = Assistant([writer], image_url_template=TEMPLATE)

    assert run(assistant, "make it blue", history)[-1][1]["route"] == "image"
    assert run(assistant, "where do foxes live?", history)[-1][1]["route"] != "image"


def test_the_image_task_draws_whatever_the_wording():
    writer = Provider("groq", [["A quiet harbour"]])
    done = run(
        Assistant([writer], image_url_template=TEMPLATE),
        "a quiet harbour",
        options=Options(task="image"),
    )[-1][1]
    assert done["images"][0]["prompt"] == "A quiet harbour"


def test_pictures_keep_their_fast_order_in_best_mode():
    available = {"claude", "groq", "gemini"}
    assert provider_order("best", "image", "claude,gemini,groq", available) == [
        "groq",
        "gemini",
        "claude",
    ]


# --- Attachments, style and instructions --------------------------------------------


def test_attached_files_go_before_the_question_and_images_ride_along():
    attachments = [
        Attachment(name="notes.md", kind="text", text="Deadline is Friday."),
        Attachment(name="chart.png", kind="image", mime="image/png", data=PNG),
    ]
    [turn] = conversation("When is the deadline?", [], [], attachments)
    assert turn.content.startswith('<file name="notes.md">\nDeadline is Friday.\n</file>')
    assert turn.content.endswith("When is the deadline?")
    assert turn.images == [Image("image/png", PNG)]


def test_attached_images_go_to_the_services_that_see_them():
    assert classify("what is in this picture?", None, images=True) == "vision"
    gemini = Provider("gemini", [["A bar chart."]])
    groq = Provider("groq", [])
    options = Options(
        attachments=[Attachment(name="a.png", kind="image", mime="image/png", data=PNG)]
    )
    done = run(Assistant([groq, gemini]), "draw conclusions from this", options=options)[-1][1]
    # "draw …" with an image attached is about the image, not a request for a picture.
    assert (done["route"], done["provider"]) == ("vision", "Gemini")
    assert gemini.calls[0].turns[-1].images == [Image("image/png", PNG)]


def test_style_instructions_and_temperature_reach_the_model():
    gemini = Provider("gemini", [["Short."]])
    options = Options(style="concise", instructions="Answer in French.", temperature=0.2)
    run(Assistant([gemini]), "What is HMAC?", options=options)
    call = gemini.calls[0]
    assert "Keep this answer short" in call.system
    assert call.system.endswith("Answer in French.")
    assert call.temperature == 0.2


def test_the_default_style_adds_nothing_to_the_prompt():
    assert system_prompt() == system_prompt(style="balanced", instructions="  ")
    assert "thorough" in system_prompt(style="detailed")


# --- Providers: images and temperature ------------------------------------------------


class StubHttp:
    def __init__(self, lines):
        self.lines = lines
        self.requests = []

    @contextmanager
    def stream(self, method, url, headers, json):
        self.requests.append(json)
        yield SimpleNamespace(
            status_code=200, iter_lines=lambda: iter(self.lines), read=lambda: b""
        )


def test_gemini_gets_images_inline_and_the_temperature():
    http = StubHttp(['data: {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}'])
    provider = GeminiProvider(http, "key", ["g"], 100)
    turns = [Turn("user", "what is this?", [Image("image/png", PNG)])]
    list(provider.stream("g", "sys", turns, Outcome(), web=False, temperature=0.4))

    [request] = http.requests
    assert request["contents"][0]["parts"] == [
        {"inline_data": {"mime_type": "image/png", "data": PNG}},
        {"text": "what is this?"},
    ]
    assert request["generationConfig"]["temperature"] == 0.4


def test_openai_compatible_services_get_images_as_content_parts():
    http = StubHttp(['data: {"choices": [{"delta": {"content": "ok"}}]}', "data: [DONE]"])
    provider = OpenAICompatibleProvider("groq", "Groq", "https://g", http, "k", ["m"], 100)
    turns = [
        Turn("user", "hi"),
        Turn("assistant", "hello"),
        Turn("user", "this?", [Image("image/jpeg", PNG)]),
    ]
    list(provider.stream("m", "sys", turns, Outcome(), web=False, temperature=1.1))

    [request] = http.requests
    assert request["messages"][1] == {"role": "user", "content": "hi"}
    assert request["messages"][3]["content"] == [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{PNG}"}},
        {"type": "text", "text": "this?"},
    ]
    assert request["temperature"] == 1.1


def test_claude_gets_image_blocks_and_a_temperature_within_its_range():
    requests = []

    @contextmanager
    def stream(**kwargs):
        requests.append(kwargs)
        final = SimpleNamespace(model="claude", stop_reason="end_turn")
        yield SimpleNamespace(text_stream=iter(["ok"]), get_final_message=lambda: final)

    provider = ClaudeProvider(SimpleNamespace(messages=SimpleNamespace(stream=stream)), ["c"], 100)
    turns = [Turn("user", "this?", [Image("image/png", PNG)])]
    list(provider.stream("c", "sys", turns, Outcome(), web=False, temperature=1.8))

    assert requests[0]["messages"][0]["content"][0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": PNG},
    }
    assert requests[0]["temperature"] == 1.0


# --- /ask with the new fields ----------------------------------------------------------


@pytest.fixture
def chat(client):
    from app.assistant import get_assistant
    from app.main import app

    holder = SimpleNamespace(assistant=None)
    app.dependency_overrides[get_assistant] = lambda: holder.assistant
    yield holder
    app.dependency_overrides.pop(get_assistant, None)


def test_a_json_question_with_a_style_goes_to_the_assistant(client, chat, answerer):
    gemini = Provider("gemini", [["Brief answer."]])
    chat.assistant = Assistant([gemini])
    response = client.post("/ask", json={"question": "What is HMAC?", "style": "concise"})

    assert response.status_code == 200
    assert response.json()["provider"] == "Gemini"
    assert answerer.calls == []  # not the sources-only answerer


def test_a_picture_request_returns_its_image(client, chat):
    chat.assistant = Assistant([Provider("groq", [["A lighthouse"]])], image_url_template=TEMPLATE)
    response = client.post("/ask", json={"question": "a lighthouse", "task": "image"})
    assert response.json()["images"][0]["prompt"] == "A lighthouse"


@pytest.mark.parametrize(
    "attachment",
    [
        {"name": "a.png", "kind": "image", "mime": "image/png"},  # no data
        {"name": "a.txt", "kind": "text"},  # no text
        {"name": "a.bmp", "kind": "image", "mime": "image/bmp", "data": PNG},  # unsupported type
    ],
)
def test_incomplete_attachments_are_rejected(client, chat, attachment):
    response = client.post("/ask", json={"question": "q", "attachments": [attachment]})
    assert response.status_code == 422


def test_attached_text_is_limited_in_all(client, chat):
    big = {"name": "a.txt", "kind": "text", "text": "x" * 150_000}
    response = client.post("/ask", json={"question": "q", "attachments": [big, big, big]})
    assert response.status_code == 422
    assert "limited" in response.text


# --- /attachments ---------------------------------------------------------------------


def test_a_text_file_is_read_for_attaching(plain_client):
    response = plain_client.post(
        "/attachments", files={"file": ("main.py", b"print('hi')\n", "text/x-python")}
    )
    assert response.status_code == 200
    assert response.json() == {
        "name": "main.py",
        "kind": "text",
        "text": "print('hi')",
        "truncated": False,
    }


def test_an_html_file_is_read_as_its_text(plain_client):
    html = (
        b"<html><head><title>T</title></head><body><article><h1>Notes</h1>"
        + (b"<p>The launch moves to Friday because the review ran long this week.</p>" * 3)
        + b"</article></body></html>"
    )
    response = plain_client.post("/attachments", files={"file": ("page.html", html, "text/html")})
    assert response.status_code == 200
    assert "launch moves to Friday" in response.json()["text"]


def test_long_text_is_cut_and_says_so(plain_client):
    response = plain_client.post(
        "/attachments", files={"file": ("big.txt", b"word " * 40_000, "text/plain")}
    )
    body = response.json()
    assert body["truncated"] is True
    assert len(body["text"]) == 150_000


@pytest.mark.parametrize("content", [b"\x00\x01\x02binary", b"   \n  "], ids=["binary", "blank"])
def test_files_without_readable_text_are_refused(plain_client, content):
    response = plain_client.post(
        "/attachments", files={"file": ("x.bin", content, "application/octet-stream")}
    )
    assert response.status_code == 422


# --- /shares ----------------------------------------------------------------------------


MESSAGES = [
    {"role": "user", "text": "What is HMAC?"},
    {"role": "assistant", "response": {"answer": "A keyed hash."}},
]


def test_a_shared_chat_can_be_read_back_by_its_id(client):
    created = client.post("/shares", json={"title": "What is HMAC?", "messages": MESSAGES})
    assert created.status_code == 201
    share = created.json()
    assert len(share["id"]) >= 12

    read = client.get(f"/shares/{share['id']}")
    assert read.status_code == 200
    assert read.json()["messages"] == MESSAGES
    assert read.json()["title"] == "What is HMAC?"


def test_an_unknown_share_is_not_found(client):
    assert client.get("/shares/nope").status_code == 404


def test_a_share_needs_messages_with_roles(client):
    response = client.post("/shares", json={"title": "t", "messages": [{"text": "hi"}]})
    assert response.status_code == 422


def test_a_share_is_limited_in_size(client):
    big = [{"role": "user", "text": "x" * 1_000_000}] * 3
    response = client.post("/shares", json={"title": "t", "messages": big})
    assert response.status_code == 413
    assert json.loads(response.text)["detail"].startswith("This chat is too large")
