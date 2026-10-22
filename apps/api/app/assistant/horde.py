"""AI Horde (aihorde.net): models run by volunteers, free with the anonymous key.

A request joins a queue and is polled until a worker has written the answer, so
nothing streams: the whole answer arrives at once, often after 10 to 60 seconds.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence

import httpx2

from .providers import Outcome, ProviderError, Turn

HORDE = "https://aihorde.net/api/v2"
CLIENT_AGENT = "atlas:1:github.com/muhammedarifudheen/RAG"
# Characters of prompt sent; the workers' context is a few thousand tokens.
PROMPT_CHARS = 20_000


def horde_headers(api_key: str) -> dict[str, str]:
    return {"apikey": api_key, "Client-Agent": CLIENT_AGENT}


def transcript(system: str, turns: Sequence[Turn], limit: int = PROMPT_CHARS) -> str:
    """The conversation as one prompt, ending where the assistant's reply begins. When
    too long, the oldest turns go first, then the start of the latest."""
    rendered = [
        f"### {'Assistant' if t.role == 'assistant' else 'User'}:\n{t.content}" for t in turns
    ]
    head = f"{system}\n\n"
    tail = "\n\n### Assistant:\n"
    while len(rendered) > 1 and len(head) + sum(map(len, rendered)) + len(tail) > limit:
        rendered.pop(0)
    body = "\n\n".join(rendered)
    room = limit - len(head) - len(tail)
    if len(body) > room:
        body = body[-room:]
    return head + body + tail


class HordeTextProvider:
    name = "horde"
    label = "AI Horde"

    def __init__(
        self,
        client: httpx2.Client,
        api_key: str,
        models: list[str],
        max_tokens: int = 512,
        *,
        poll_every: float = 2.0,
        give_up_after: float = 150.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.client = client
        self.api_key = api_key
        self.models = models
        self.max_tokens = max_tokens
        self.poll_every = poll_every
        self.give_up_after = give_up_after
        self.sleep = sleep

    def searches(self, model: str) -> bool:
        return False

    def stream(
        self,
        model: str,
        system: str,
        turns: Sequence[Turn],
        outcome: Outcome,
        *,
        web: bool,
        temperature: float | None = None,
    ) -> Iterator[str]:
        if any(t.images for t in turns):
            raise ProviderError("AI Horde's text models cannot see images.")
        params: dict = {"max_length": self.max_tokens, "max_context_length": 8192}
        if temperature is not None:
            params["temperature"] = max(0.01, temperature)
        headers = horde_headers(self.api_key)
        try:
            submitted = self.client.post(
                f"{HORDE}/generate/text/async",
                headers=headers,
                json={"prompt": transcript(system, turns), "params": params, "models": [model]},
            )
            if submitted.status_code >= 400:
                raise ProviderError(f"AI Horde {model}: {_message(submitted)}")
            job = submitted.json()["id"]
        except httpx2.HTTPError as error:
            raise ProviderError(f"AI Horde could not be reached: {error}") from error

        finished = False
        deadline = time.monotonic() + self.give_up_after
        try:
            while time.monotonic() < deadline:
                self.sleep(self.poll_every)
                status = self.client.get(f"{HORDE}/generate/text/status/{job}", headers=headers)
                if status.status_code >= 400:
                    raise ProviderError(f"AI Horde {model}: {_message(status)}")
                state = status.json()
                if state.get("faulted") or state.get("is_possible") is False:
                    raise ProviderError(f"AI Horde {model}: no worker can run this request.")
                if state.get("done"):
                    finished = True
                    generations = state.get("generations") or []
                    text = (generations[0].get("text") if generations else "") or ""
                    outcome.model = (generations[0].get("model") if generations else None) or model
                    # The model sometimes runs on into the next turn; cut it there.
                    text = text.split("\n### User:")[0].strip()
                    if text:
                        yield text
                    return
            raise ProviderError(f"AI Horde {model}: no answer within {self.give_up_after:.0f} s.")
        except httpx2.HTTPError as error:
            raise ProviderError(f"AI Horde could not be reached: {error}") from error
        finally:
            if not finished:
                # Give the slot back; the answer is no longer wanted.
                try:
                    self.client.delete(f"{HORDE}/generate/text/status/{job}", headers=headers)
                except httpx2.HTTPError:
                    pass


def _message(response: httpx2.Response) -> str:
    try:
        return str(response.json().get("message") or f"HTTP {response.status_code}")[:300]
    except ValueError:
        return f"HTTP {response.status_code}"
