"""Pictures from several free services at once, for a gallery.

Pollinations draws from a URL the browser loads, so it costs the server nothing.
Cloudflare, Hugging Face and AI Horde return the picture itself, which is passed on
as a data URL (Horde's own links expire after half an hour).
"""

from __future__ import annotations

import base64
import logging
import queue
import random
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import httpx2

from .horde import HORDE, horde_headers

logger = logging.getLogger("atlas.api.assistant")


class ImageError(Exception):
    pass


@dataclass(frozen=True)
class Drawn:
    url: str
    service: str


class ImageService(Protocol):
    label: str

    def draw(self, prompt: str, seed: int) -> str:
        """The picture's URL (or data URL). Raises ImageError."""
        ...


def _data_url(content: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(content).decode()}"


class PollinationsImages:
    label = "Pollinations"

    def __init__(self, template: str):
        self.template = template

    def draw(self, prompt: str, seed: int) -> str:
        return self.template.format(prompt=quote(prompt, safe=""), seed=seed)


class CloudflareImages:
    label = "Cloudflare FLUX"

    def __init__(self, client: httpx2.Client, account: str, token: str, model: str):
        self.client, self.account, self.token, self.model = client, account, token, model

    def draw(self, prompt: str, seed: int) -> str:
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.account}/ai/run/{self.model}"
        try:
            response = self.client.post(
                url,
                headers={"Authorization": f"Bearer {self.token}"},
                json={"prompt": prompt, "steps": 4, "seed": seed},
            )
        except httpx2.HTTPError as error:
            raise ImageError(f"Cloudflare could not be reached: {error}") from error
        if response.status_code >= 400:
            raise ImageError(f"Cloudflare: HTTP {response.status_code}")
        image = (response.json().get("result") or {}).get("image")
        if not image:
            raise ImageError("Cloudflare returned no image.")
        return f"data:image/jpeg;base64,{image}"


class HuggingFaceImages:
    label = "Hugging Face FLUX"

    def __init__(self, client: httpx2.Client, token: str, model: str):
        self.client, self.token, self.model = client, token, model

    def draw(self, prompt: str, seed: int) -> str:
        url = f"https://router.huggingface.co/hf-inference/models/{self.model}"
        try:
            response = self.client.post(
                url,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "image/jpeg"},
                json={"inputs": prompt, "parameters": {"seed": seed}},
            )
        except httpx2.HTTPError as error:
            raise ImageError(f"Hugging Face could not be reached: {error}") from error
        mime = response.headers.get("content-type", "").split(";")[0]
        if response.status_code >= 400 or not mime.startswith("image/"):
            raise ImageError(f"Hugging Face: HTTP {response.status_code}")
        return _data_url(response.content, mime)


class HordeImages:
    label = "AI Horde"

    def __init__(
        self,
        client: httpx2.Client,
        api_key: str,
        models: list[str],
        *,
        poll_every: float = 3.0,
        give_up_after: float = 120.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.client, self.api_key, self.models = client, api_key, models
        self.poll_every, self.give_up_after, self.sleep = poll_every, give_up_after, sleep

    def draw(self, prompt: str, seed: int) -> str:
        headers = horde_headers(self.api_key)
        try:
            submitted = self.client.post(
                f"{HORDE}/generate/async",
                headers=headers,
                json={
                    "prompt": prompt[:1000],
                    "params": {
                        "width": 512,
                        "height": 512,
                        "steps": 20,
                        "n": 1,
                        "sampler_name": "k_euler_a",
                        "cfg_scale": 7,
                        "seed": str(seed),
                    },
                    "nsfw": False,
                    "censor_nsfw": True,
                    "models": self.models,
                    "r2": True,
                },
            )
            if submitted.status_code >= 400:
                raise ImageError(f"AI Horde: HTTP {submitted.status_code}")
            job = submitted.json()["id"]
            deadline = time.monotonic() + self.give_up_after
            while time.monotonic() < deadline:
                self.sleep(self.poll_every)
                check = self.client.get(f"{HORDE}/generate/check/{job}", headers=headers).json()
                if check.get("faulted") or check.get("is_possible") is False:
                    raise ImageError("AI Horde has no worker for this picture now.")
                if check.get("done"):
                    status = self.client.get(f"{HORDE}/generate/status/{job}", headers=headers)
                    generation = (status.json().get("generations") or [{}])[0]
                    if generation.get("censored") or not generation.get("img"):
                        raise ImageError("AI Horde returned no picture.")
                    picture = self.client.get(generation["img"])
                    mime = picture.headers.get("content-type", "image/webp").split(";")[0]
                    return _data_url(picture.content, mime)
            self.client.delete(f"{HORDE}/generate/status/{job}", headers=headers)
            raise ImageError("AI Horde did not finish in time.")
        except (httpx2.HTTPError, ValueError, KeyError) as error:
            raise ImageError(f"AI Horde failed: {error}") from error


def gallery(
    services: Sequence[ImageService], prompt: str, size: int, max_wait: float
) -> Iterator[Drawn]:
    """Draws `prompt` on up to `size` services in parallel, yielding each picture as it
    is ready, until all are done or `max_wait` seconds pass. With fewer services than
    `size`, Pollinations draws the rest with other seeds."""
    chosen = list(services[:size])
    pollinations = [s for s in services if isinstance(s, PollinationsImages)]
    while pollinations and len(chosen) < size:
        chosen.append(pollinations[0])
    if not chosen:
        return
    results: queue.Queue = queue.Queue()

    def run(service: ImageService) -> None:
        started = time.monotonic()
        try:
            url = service.draw(prompt, random.randint(1, 2_000_000_000))
            results.put(Drawn(url, service.label))
        except ImageError as error:
            logger.info(
                "image %s: failed in %.1fs (%s)", service.label, time.monotonic() - started, error
            )
            results.put(None)

    for service in chosen:
        threading.Thread(target=run, args=(service,), daemon=True).start()
    deadline = time.monotonic() + max_wait
    for _ in chosen:
        try:
            drawn = results.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            return
        if drawn is not None:
            yield drawn
