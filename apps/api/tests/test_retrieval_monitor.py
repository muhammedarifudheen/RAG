"""The zero-retrieval detector: a broken index is flagged, once, and the health endpoint says so."""

import pytest
from fastapi.testclient import TestClient

from app.retrieval import monitor as monitor_module
from app.retrieval.monitor import COOLDOWN_SECONDS, RetrievalMonitor


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(**kw):
    sent = []
    clock = Clock()
    mon = RetrievalMonitor(notify=sent.append, clock=clock, **kw)
    return mon, sent, clock


def feed(mon, empty, found, score=8.0):
    for _ in range(empty):
        mon.record(0, None, 0)
    for _ in range(found):
        mon.record(9, score, 3)


def test_a_fresh_monitor_is_quiet():
    mon, sent, _ = make()
    feed(mon, empty=5, found=0)  # every query empty, but only five: too few to judge
    status = mon.status()
    assert status["state"] == "insufficient_data" and status["alert"] is False
    assert sent == []


def test_a_healthy_window_does_not_alert_and_reports_its_median():
    mon, sent, _ = make()
    feed(mon, empty=1, found=19)
    status = mon.status()
    assert status["state"] == "ok" and status["alert"] is False
    assert status["empty"] == 1 and status["queries"] == 20 and status["empty_rate"] == 0.05
    assert status["p50_top_rerank_score"] == 8.0
    assert sent == []


def test_over_twenty_percent_empty_alerts_once_with_a_webhook():
    mon, sent, _ = make()
    feed(mon, empty=0, found=16)
    feed(mon, empty=5, found=0)  # 5 of 21 is 24%: crossed
    assert [p["state"] for p in sent] == ["alert"]
    payload = sent[0]
    assert payload["check"] == "retrieval" and payload["empty"] == 5
    assert payload["empty_rate"] > 0.2 and "broken" in payload["message"]
    feed(mon, empty=3, found=0)  # still over: no second webhook
    assert len(sent) == 1
    status = mon.status()
    assert status["alert"] is True and status["state"] == "alert" and status["last_alert_at"]


def test_exactly_twenty_percent_is_not_over():
    mon, sent, _ = make()
    feed(mon, empty=0, found=16)
    feed(mon, empty=4, found=0)  # 4 of 20, never over on the way
    assert mon.status()["alert"] is False and sent == []


def test_it_says_when_it_recovers_after_the_cooldown():
    mon, sent, clock = make()
    feed(mon, empty=6, found=10)
    assert [p["state"] for p in sent] == ["alert"]
    clock.now += COOLDOWN_SECONDS + 1
    feed(mon, empty=0, found=100)  # the window turns over: no empties left
    assert [p["state"] for p in sent] == ["alert", "recovered"]
    assert mon.status()["state"] == "ok"


def test_a_rate_hovering_at_the_line_does_not_flap():
    mon, sent, _ = make()
    feed(mon, empty=6, found=10)  # alert
    feed(mon, empty=0, found=30)  # recovers inside the cooldown: nothing is sent yet
    assert [p["state"] for p in sent] == ["alert"]


def test_the_window_keeps_only_the_last_hundred():
    mon, _, _ = make()
    feed(mon, empty=50, found=0)
    feed(mon, empty=0, found=100)
    status = mon.status()
    assert status["queries"] == 100 and status["empty"] == 0


def test_a_failing_webhook_never_breaks_a_query():
    def boom(_):
        raise RuntimeError("no network")

    mon = RetrievalMonitor(notify=boom, clock=Clock())
    feed(mon, empty=12, found=0)  # alerts; the failure is swallowed
    assert mon.status()["alert"] is True


def test_the_answer_state_is_kept_with_the_query():
    mon, _, _ = make()
    entry = mon.record(9, 7.0, 3)
    assert mon.status()["answer_states"] == {"pending": 1}
    mon.finish(entry, "VERIFIED")
    assert mon.status()["answer_states"] == {"VERIFIED": 1}
    assert entry.chunks_retrieved == 9 and entry.final_chunk_count == 3


def test_an_empty_monitor_reports_nulls():
    status = RetrievalMonitor(notify=lambda _: None).status()
    assert status["empty_rate"] is None and status["p50_top_rerank_score"] is None
    assert status["state"] == "insufficient_data"


@pytest.fixture
def client(monkeypatch):
    from app.main import app

    mon = RetrievalMonitor(notify=lambda _: None)
    monkeypatch.setattr(monitor_module, "_monitor", mon)
    return TestClient(app), mon


def test_the_health_endpoint_reports_the_window(client):
    http, mon = client
    feed(mon, empty=0, found=12)
    body = http.get("/health/retrieval").json()
    assert body["state"] == "ok" and body["queries"] == 12 and body["empty_rate"] == 0.0
    assert body["threshold"] == 0.2 and body["p50_top_rerank_score"] == 8.0


def test_the_health_endpoint_alerts_and_can_answer_503(client):
    http, mon = client
    feed(mon, empty=8, found=4)
    plain = http.get("/health/retrieval")
    assert plain.status_code == 200 and plain.json()["alert"] is True  # always 200 by default
    assert http.get("/health/retrieval", params={"fail": "true"}).status_code == 503
