"""The council of agents, AI Horde, the picture gallery and the service registry."""

import threading
import time
from types import SimpleNamespace

import pytest

from app.assistant import Assistant
from app.assistant.horde import HordeTextProvider, transcript
from app.assistant.images import Drawn, HordeImages, ImageError, PollinationsImages, gallery
from app.assistant.prompt import FOLLOW_UPS
from app.assistant.providers import Image, Outcome, ProviderError, Turn
from app.assistant.services import SERVICES, configured, openrouter_free_models


class Agent:
    """A stand-in service whose models each give one canned reply (text, an exception,
    or a pause), safe to call from several threads at once."""

    def __init__(self, name, replies, delay=0.0, searches=False):
        self.name = name
        self.label = name.title()
        self.replies = dict(replies)  # model -> reply
        self.models = list(self.replies)
        self.delay = delay
        self.web = searches
        self.calls = []
        self.lock = threading.Lock()

    def searches(self, model):
        return self.web

    def stream(self, model, system, turns, outcome, *, web, temperature=None):
        with self.lock:
            self.calls.append(SimpleNamespace(model=model, system=system, turns=turns))
        reply = self.replies[model]
        if isinstance(reply, (int, float)):
            time.sleep(reply)
            reply = "late"
        elif self.delay:
            time.sleep(self.delay)
        if isinstance(reply, Exception):
            raise reply
        outcome.model = model
        yield reply


def council(*agents, size=12, grace=0.3, max_wait=3.0, **options):
    return Assistant(
        list(agents), council_size=size, council_grace=grace, council_max_wait=max_wait, **options
    )


def events_of(assistant, question="What is HMAC?", **kwargs):
    return list(assistant.respond(question, [], (), "auto", **kwargs))


def test_every_agent_answers_and_one_model_merges_their_drafts():
    gemini = Agent(
        "gemini",
        {
            "g1": "HMAC is a keyed hash.",
            "g2": "HMAC uses a secret key with a hash.",
        },
    )
    groq = Agent("groq", {"q1": "HMAC authenticates messages."})
    events = events_of(council(gemini, groq))

    names = [name for name, _ in events]
    assert names[0] == "route"
    seated = [data for name, data in events if name == "agent" and data["state"] == "thinking"]
    # Services take turns: each one's first model, then the next models.
    assert [(a["service"], a["model"]) for a in seated] == [
        ("Gemini", "g1"),
        ("Groq", "q1"),
        ("Gemini", "g2"),
    ]
    assert names.count("merging") == 1
    done = events[-1][1]
    assert names[-1] == "done"
    assert done["provider"] == "Atlas council"
    assert len(done["agents"]) == 3

    # The merger (here Gemini's first model, answering again) saw all three drafts.
    merge = gemini.calls[-1]
    assert "Several independent assistants have drafted answers" in merge.system
    last = merge.turns[-1].content
    assert last.count("<draft n=") == 3
    for draft in ("keyed hash", "secret key", "authenticates messages"):
        assert draft in last


def test_the_merged_answer_streams_and_keeps_its_follow_ups():
    gemini = Agent("gemini", {"g1": "Draft one."})
    groq = Agent("groq", {"q1": "Draft two."})
    assistant = council(gemini, groq)
    # The merger's reply: Gemini's first model is asked a second time.
    replies = iter(["Draft one.", f"The merged answer.\n{FOLLOW_UPS}\nWhy?\nHow?\nWhere?"])
    original = gemini.stream

    def stream(model, system, turns, outcome, *, web, temperature=None):
        gemini.replies[model] = next(replies)
        yield from original(model, system, turns, outcome, web=web)

    gemini.stream = stream
    events = events_of(assistant)
    text = "".join(data["text"] for name, data in events if name == "delta")
    assert text.strip() == "The merged answer."
    assert events[-1][1]["suggestions"] == ["Why?", "How?", "Where?"]


def test_a_failing_agent_is_replaced_by_the_next_model_in_line():
    gemini = Agent("gemini", {"g1": ProviderError("quota"), "g2": "Second model's draft."})
    groq = Agent("groq", {"q1": "Groq's draft."})
    events = events_of(council(gemini, groq, size=2))

    states = [(d["id"], d["state"]) for name, d in events if name == "agent"]
    assert (0, "failed") in states
    # g2 was held in reserve and took the failed seat.
    seated = [d["model"] for name, d in events if name == "agent" and d["state"] == "thinking"]
    assert seated == ["g1", "q1", "g2"]
    assert len(events[-1][1]["agents"]) == 2


def test_slow_agents_are_not_waited_for_once_two_have_answered():
    fast = Agent("gemini", {"g1": "Fast draft."})
    also = Agent("groq", {"q1": "Another fast draft."})
    slow = Agent("mistral", {"m1": 5})  # sleeps five seconds
    started = time.monotonic()
    events = events_of(council(fast, also, slow, grace=0.2))
    assert time.monotonic() - started < 3
    assert any(d.get("state") == "skipped" for name, d in events if name == "agent")
    assert events[-1][0] == "done"
    assert len(events[-1][1]["agents"]) == 2


def test_one_draft_is_the_answer_without_a_merge():
    gemini = Agent("gemini", {"g1": "The only answer."})
    groq = Agent("groq", {"q1": ProviderError("down")})
    events = events_of(council(gemini, groq))
    assert "merging" not in [name for name, _ in events]
    assert events[-1][1]["answer"] == "The only answer."
    assert events[-1][1]["provider"] == "Gemini"


def test_when_no_model_can_merge_the_best_suited_draft_stands():
    gemini = Agent("gemini", {"g1": "Gemini's draft."})
    groq = Agent("groq", {"q1": "Groq's draft."})
    assistant = council(gemini, groq)
    for agent in (gemini, groq):
        original = agent.stream

        def stream(model, system, turns, outcome, *, web, temperature=None, _original=original):
            if "Several independent assistants" in system:
                raise ProviderError("no merge today")
            yield from _original(model, system, turns, outcome, web=web)

        agent.stream = stream
    done = events_of(assistant)[-1][1]
    assert done["answer"] == "Gemini's draft."  # Gemini comes first for a general question


def test_when_every_agent_fails_the_reason_is_given():
    events = events_of(
        council(
            Agent("gemini", {"g1": ProviderError("quota")}),
            Agent("groq", {"q1": ProviderError("down")}),
        )
    )
    assert events[-1][0] == "error"
    assert "Every AI service failed" in events[-1][1]["detail"]


def test_services_that_cannot_see_images_sit_out_when_images_are_attached():
    from app.assistant import Options
    from app.schemas import Attachment

    gemini = Agent("gemini", {"g1": "A red square."})
    horde = Agent("horde", {"h1": "I cannot see it."})
    pollinations = Agent("pollinations", {"p1": "No idea."})
    options = Options(
        attachments=[Attachment(name="a.png", kind="image", mime="image/png", data="AAAA")]
    )
    events = events_of(council(gemini, horde, pollinations), "What is this?", options=options)
    assert horde.calls == [] and pollinations.calls == []
    assert events[-1][1]["answer"] == "A red square."


def test_a_council_of_one_is_the_single_model_path():
    gemini = Agent("gemini", {"g1": "Alone."})
    events = events_of(Assistant([gemini], council_size=1))
    assert not any(name == "agent" for name, _ in events)
    assert events[-1][1]["answer"] == "Alone."


# --- AI Horde -----------------------------------------------------------------------------


class StubHorde:
    """Stands in for httpx2.Client: the queue answers after `polls` status checks."""

    def __init__(self, text="Lima.", polls=2, possible=True):
        self.text, self.polls, self.possible = text, polls, possible
        self.posted, self.deleted = [], []

    def post(self, url, headers, json):
        self.posted.append(json)
        return SimpleNamespace(status_code=202, json=lambda: {"id": "job1"})

    def get(self, url, headers=None):
        self.polls -= 1
        done = self.polls <= 0
        body = {"done": done, "is_possible": self.possible, "faulted": False}
        if done:
            body["generations"] = [{"text": self.text + "\n### User:\nnext turn", "model": "gemma"}]
        return SimpleNamespace(status_code=200, json=lambda: body)

    def delete(self, url, headers=None):
        self.deleted.append(url)


def test_horde_queues_the_request_and_returns_the_answer_when_done():
    http = StubHorde()
    provider = HordeTextProvider(http, "0000000000", ["gemma"], sleep=lambda _: None)
    outcome = Outcome()
    text = "".join(
        provider.stream(
            "gemma", "Be brief.", [Turn("user", "Capital of Peru?")], outcome, web=False
        )
    )
    assert text == "Lima."  # the run-on into the next turn is cut
    assert outcome.model == "gemma"
    assert http.posted[0]["models"] == ["gemma"]
    assert http.posted[0]["prompt"].endswith("### User:\nCapital of Peru?\n\n### Assistant:\n")
    assert http.deleted == []


def test_horde_gives_up_and_frees_its_slot_when_no_worker_can_answer():
    http = StubHorde(possible=False, polls=5)
    provider = HordeTextProvider(http, "k", ["gemma"], sleep=lambda _: None)
    with pytest.raises(ProviderError, match="no worker"):
        list(provider.stream("gemma", "s", [Turn("user", "q")], Outcome(), web=False))
    assert http.deleted


def test_horde_cannot_see_images():
    provider = HordeTextProvider(StubHorde(), "k", ["gemma"], sleep=lambda _: None)
    with pytest.raises(ProviderError, match="images"):
        list(
            provider.stream(
                "gemma", "s", [Turn("user", "q", [Image("image/png", "AA")])], Outcome(), web=False
            )
        )


def test_a_long_conversation_is_cut_from_the_oldest_turn():
    turns = [
        Turn("user", "old " * 3000),
        Turn("assistant", "reply"),
        Turn("user", "latest question"),
    ]
    prompt = transcript("System.", turns, limit=2000)
    assert len(prompt) <= 2000
    assert prompt.startswith("System.")
    assert "latest question" in prompt
    assert "old old" not in prompt


# --- Pictures -------------------------------------------------------------------------------


class Painter:
    def __init__(self, label, result, delay=0.0):
        self.label, self.result, self.delay = label, result, delay

    def draw(self, prompt, seed):
        time.sleep(self.delay)
        if isinstance(self.result, Exception):
            raise self.result
        return f"{self.result}#{prompt}"


def test_the_gallery_draws_on_several_services_and_skips_failures():
    painters = [
        Painter("Cloudflare FLUX", "data:image/jpeg;base64,AA"),
        Painter("AI Horde", ImageError("busy")),
        PollinationsImages("https://draw.example/{prompt}?seed={seed}"),
    ]
    drawn = list(gallery(painters, "a fox", size=4, max_wait=2))
    services = sorted(d.service for d in drawn)
    # Each service draws once; Pollinations is not asked twice (it allows one a visitor).
    assert services == ["Cloudflare FLUX", "Pollinations"]
    assert all(isinstance(d, Drawn) for d in drawn)


def test_the_gallery_does_not_wait_past_its_limit():
    painters = [
        Painter("Slow", "x", delay=3),
        PollinationsImages("https://draw.example/{prompt}?s={seed}"),
    ]
    started = time.monotonic()
    drawn = list(gallery(painters, "a fox", size=2, max_wait=0.5))
    assert time.monotonic() - started < 2
    assert [d.service for d in drawn] == ["Pollinations"]


def test_picture_answers_stream_each_image_as_it_is_ready():
    writer = Agent("groq", {"q1": "A red fox in snow"})
    painters = [
        Painter("Cloudflare FLUX", "data:image/jpeg;base64,AA"),
        PollinationsImages("https://draw.example/{prompt}?{seed}"),
    ]
    assistant = Assistant([writer], image_services=painters, gallery_size=2)
    events = list(assistant.respond("draw a fox", [], ()))
    images = [data for name, data in events if name == "image"]
    assert sorted(i["service"] for i in images) == ["Cloudflare FLUX", "Pollinations"]
    assert len(events[-1][1]["images"]) == 2


class StubHordeImages:
    def __init__(self):
        self.calls = []

    def post(self, url, headers, json):
        self.calls.append(("post", json))
        return SimpleNamespace(status_code=202, json=lambda: {"id": "img1"})

    def get(self, url, headers=None):
        self.calls.append(("get", url))
        if "/generate/check/" in url:
            return SimpleNamespace(json=lambda: {"done": True, "is_possible": True})
        if "/generate/status/" in url:
            return SimpleNamespace(
                json=lambda: {"generations": [{"img": "https://r2.example/p.webp"}]}
            )
        return SimpleNamespace(content=b"RIFF", headers={"content-type": "image/webp"})

    def delete(self, url, headers=None):
        pass


def test_horde_pictures_are_downloaded_into_data_urls():
    http = StubHordeImages()
    painter = HordeImages(http, "k", ["Deliberate"], sleep=lambda _: None)
    url = painter.draw("a fox", 7)
    assert url == "data:image/webp;base64,UklGRg=="
    request = http.calls[0][1]
    assert request["nsfw"] is False and request["censor_nsfw"] is True
    assert request["models"] == ["Deliberate"]


# --- Services -------------------------------------------------------------------------------


def test_only_services_with_keys_and_pollinations_are_configured():
    values = {
        "groq_api_key": "gsk",
        "cloudflare_api_token": "cf",  # no account id: left out
        "pollinations_text": True,
    }
    found = configured(lambda name: values.get(name), lambda setting: ["m1"])
    assert [service.name for service, *_ in found] == ["groq", "pollinations"]
    pollinations = next(f for f in found if f[0].name == "pollinations")
    assert pollinations[1] is None  # no key sent


def test_cloudflare_needs_its_account_in_the_address():
    values = {"cloudflare_api_token": "cf", "cloudflare_account_id": "acc123"}
    [(_service, key, base, _models)] = configured(lambda n: values.get(n), lambda s: ["m"])
    assert base == "https://api.cloudflare.com/client/v4/accounts/acc123/ai/v1"
    assert key == "cf"


def test_every_service_has_a_distinct_name():
    names = [s.name for s in SERVICES]
    assert len(names) == len(set(names))


def test_openrouter_free_models_come_from_its_catalogue():
    catalogue = {
        "data": [
            {
                "id": "big/model:free",
                "context_length": 1000,
                "architecture": {"output_modalities": ["text"]},
            },
            {"id": "paid/model", "context_length": 9999},
            {"id": "vendor/content-safety:free", "context_length": 5000},
            {"id": "small/model:free", "context_length": 10},
            {
                "id": "image/maker:free",
                "context_length": 50,
                "architecture": {"output_modalities": ["image"]},
            },
        ]
    }
    http = SimpleNamespace(
        get=lambda url, timeout: SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: catalogue
        )
    )
    assert openrouter_free_models(http) == ["big/model:free", "small/model:free"]


def test_the_merge_goes_to_a_model_that_just_answered():
    # Gemini's first model is over quota; its third answered, so it merges, before
    # any model that was not part of the panel.
    gemini = Agent(
        "gemini",
        {"g1": ProviderError("quota"), "g2": ProviderError("quota"), "g3": "Lite's draft."},
    )
    groq = Agent("groq", {"q1": "Groq's draft."})
    events = events_of(council(gemini, groq))
    assert events[-1][0] == "done"
    merges = [c.model for c in gemini.calls if "Several independent" in c.system]
    assert merges == ["g3"]


@pytest.mark.parametrize(
    ("detail", "rest"),
    [
        (
            "Gemini g: You exceeded your current quota, please check your plan and billing details.",
            60,
        ),
        ("Claude c: Your credit balance is too low to access the Anthropic API.", 1800),
        ("Groq q: Rate limit reached for model", 60),
        ("Gemini g: This model is currently experiencing high demand.", 0),
        ("Mistral m: could not be reached", 0),
    ],
)
def test_failures_set_how_long_a_model_rests(detail, rest):
    from app.assistant.service import rest_after

    assert rest_after(detail) == rest


def test_a_model_out_of_quota_sits_out_the_next_question():
    gemini = Agent(
        "gemini", {"g1": ProviderError("You exceeded your current quota"), "g2": "Draft."}
    )
    groq = Agent("groq", {"q1": "Groq's draft."})
    assistant = council(gemini, groq)
    events_of(assistant)
    first = [c.model for c in gemini.calls if "Several independent" not in c.system]
    assert first[0] == "g1"

    gemini.calls.clear()
    events = events_of(assistant)
    seated = [d["model"] for name, d in events if name == "agent" and d["state"] == "thinking"]
    # g1 rests: it is seated last, after every other model.
    assert seated[-1] == "g1"
    assert seated[0] != "g1"


def test_a_busy_model_gets_one_more_try():
    tries = {"n": 0}
    gemini = Agent("gemini", {"g1": "unused"})
    original = gemini.stream

    def stream(model, system, turns, outcome, *, web, temperature=None):
        if "Several independent" not in system:
            tries["n"] += 1
            if tries["n"] == 1:
                raise ProviderError("This model is currently experiencing high demand.")
        gemini.replies[model] = "Second try worked."
        yield from original(model, system, turns, outcome, web=web)

    gemini.stream = stream
    from app.assistant import service

    service.RETRY_PAUSE, saved = 0.0, service.RETRY_PAUSE
    try:
        done = events_of(council(gemini, Agent("groq", {"q1": ProviderError("down")})))[-1]
    finally:
        service.RETRY_PAUSE = saved
    assert done[0] == "done"
    assert done[1]["answer"] == "Second try worked."
    assert tries["n"] == 2
