"""Pictures from several free services at once, for a gallery.

Pollinations draws from a URL the browser loads, so it costs the server nothing.
Cloudflare, Hugging Face, Together, Gemini and AI Horde (one agent per model) return
the picture itself, which is passed on as a data URL (Horde's own links expire after
half an hour).
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


# What diffusion models are told to avoid (Stable Diffusion's "negative prompt").
NEGATIVE = (
    "blurry, low quality, lowres, jpeg artifacts, deformed, distorted, disfigured, bad anatomy, "
    "extra limbs, extra fingers, watermark, signature, text, logo, frame, cropped"
)


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


class TogetherImages:
    label = "Together FLUX"

    def __init__(self, client: httpx2.Client, token: str, model: str):
        self.client, self.token, self.model = client, token, model

    def draw(self, prompt: str, seed: int) -> str:
        try:
            response = self.client.post(
                "https://api.together.xyz/v1/images/generations",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "width": 1024,
                    "height": 1024,
                    "steps": 4,
                    "n": 1,
                    "seed": seed % 2_147_483_647,
                    "response_format": "b64_json",
                },
            )
        except httpx2.HTTPError as error:
            raise ImageError(f"Together could not be reached: {error}") from error
        if response.status_code >= 400:
            raise ImageError(f"Together: HTTP {response.status_code}")
        data = (response.json().get("data") or [{}])[0]
        if data.get("b64_json"):
            return f"data:image/jpeg;base64,{data['b64_json']}"
        if data.get("url"):
            return data["url"]
        raise ImageError("Together returned no image.")


class GeminiImages:
    """Gemini's image models ("Nano Banana"). Google gives these no free quota, so they
    are only used when GEMINI_IMAGES is on (a key with billing)."""

    label = "Gemini"

    def __init__(self, client: httpx2.Client, api_key: str, model: str):
        self.client, self.api_key, self.model = client, api_key, model

    def draw(self, prompt: str, seed: int) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        )
        try:
            response = self.client.post(
                url,
                headers={"x-goog-api-key": self.api_key},
                json={
                    "contents": [{"parts": [{"text": f"Create this picture: {prompt}"}]}],
                    "generationConfig": {"responseModalities": ["IMAGE"], "seed": seed % 2**31},
                },
            )
        except httpx2.HTTPError as error:
            raise ImageError(f"Gemini could not be reached: {error}") from error
        if response.status_code >= 400:
            raise ImageError(f"Gemini: HTTP {response.status_code}")
        for candidate in response.json().get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                    return f"data:{mime};base64,{inline['data']}"
        raise ImageError("Gemini returned no image.")


def _horde_size(models: list[str]) -> int:
    """SDXL and FLUX models draw at 1024 pixels; older Stable Diffusion ones at 512."""
    return 1024 if any(("XL" in m or "Flux" in m or "FLUX" in m) for m in models) else 512


class HordeImages:
    label = "AI Horde"

    def __init__(
        self,
        client: httpx2.Client,
        api_key: str,
        models: list[str],
        *,
        label: str | None = None,
        poll_every: float = 3.0,
        give_up_after: float = 120.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.client, self.api_key, self.models = client, api_key, models
        self.poll_every, self.give_up_after, self.sleep = poll_every, give_up_after, sleep
        if label:
            self.label = label

    def draw(self, prompt: str, seed: int) -> str:
        headers = horde_headers(self.api_key)
        try:
            submitted = self.client.post(
                f"{HORDE}/generate/async",
                headers=headers,
                json={
                    # Horde's syntax for a negative prompt: after "###".
                    "prompt": f"{prompt[:900]} ### {NEGATIVE}",
                    "params": {
                        "width": _horde_size(self.models),
                        "height": _horde_size(self.models),
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
    is ready, until all are done or `max_wait` seconds pass. Each service draws once:
    free Pollinations gives a visitor one picture every 45 seconds, and a second one
    would only show its "free limit reached" card."""
    chosen = list(services[:size])
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
