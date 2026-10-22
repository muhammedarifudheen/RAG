"""The model services the assistant can use, each streaming its answer as text.

Gemini is called over its REST API and may search Google for the answer. Most
others (Groq, OpenRouter, Mistral and the rest in services.py) speak the OpenAI
chat-completions protocol, so one class serves them all. Claude goes through
Anthropic's SDK; AI Horde has its own queue (horde.py).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import anthropic
import httpx2

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


@dataclass
class Image:
    mime: str  # image/png, image/jpeg, image/webp or image/gif
    data: str  # base64


@dataclass
class Turn:
    role: str  # "user" or "assistant"
    content: str
    images: list[Image] = field(default_factory=list)


@dataclass
class Outcome:
    """Filled in while a stream runs: what served it and how it ended."""

    model: str = ""
    complete: bool = True
    web_sources: list[dict[str, str]] = field(default_factory=list)


class ProviderError(Exception):
    """This provider or model could not answer; the assistant tries the next one."""


class Provider(Protocol):
    name: str
    label: str
    models: list[str]

    def searches(self, model: str) -> bool:
        """Whether this model can search the web right now."""
        ...

    def stream(
        self,
        model: str,
        system: str,
        turns: Sequence[Turn],
        outcome: Outcome,
        *,
        web: bool,
        temperature: float | None = None,
    ) -> Iterator[str]: ...


def _reason(response: httpx2.Response) -> str:
    """The service's own error message, short."""
    try:
        body = json.loads(response.read())
        error = body.get("error", body) if isinstance(body, dict) else body
        message = error.get("message") if isinstance(error, dict) else error
    except (ValueError, AttributeError):
        message = None
    return str(message or f"HTTP {response.status_code}")[:300]


def _sse_data(response: httpx2.Response) -> Iterator[str]:
    """The `data:` payloads of a server-sent-events response."""
    for line in response.iter_lines():
        if line.startswith("data:"):
            yield line[5:].strip()


class GeminiProvider:
    """Gemini, which can ground its answer in a Google search.

    The search tool has its own quota, which a free key may not have. When Google
    refuses it, the same question is asked again without it, and the tool is left
    off for an hour so later questions do not pay for the refusal first.
    """

    name = "gemini"
    label = "Gemini"
    SEARCH_COOLDOWN = 3600.0

    def __init__(self, client: httpx2.Client, api_key: str, models: list[str], max_tokens: int):
        self.client = client
        self.api_key = api_key
        self.models = models
        self.max_tokens = max_tokens
        self.search_off_until = 0.0

    def searches(self, model: str) -> bool:
        return time.monotonic() >= self.search_off_until

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
        config: dict = {"maxOutputTokens": self.max_tokens}
        if temperature is not None:
            config["temperature"] = temperature
        payload: dict = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [
                {
                    "role": "model" if t.role == "assistant" else "user",
                    "parts": [
                        *({"inline_data": {"mime_type": i.mime, "data": i.data}} for i in t.images),
                        {"text": t.content},
                    ],
                }
                for t in turns
            ],
            "generationConfig": config,
        }
        if web and self.searches(model):
            try:
                yield from self._stream(
                    model, {**payload, "tools": [{"google_search": {}}]}, outcome
                )
                return
            except _SearchRefused:
                self.search_off_until = time.monotonic() + self.SEARCH_COOLDOWN
        yield from self._stream(model, payload, outcome)

    def _stream(self, model: str, payload: dict, outcome: Outcome) -> Iterator[str]:
        url = f"{GEMINI_BASE}/{model}:streamGenerateContent?alt=sse"
        try:
            with self.client.stream(
                "POST", url, headers={"x-goog-api-key": self.api_key}, json=payload
            ) as response:
                if response.status_code == 429 and "tools" in payload:
                    raise _SearchRefused
                if response.status_code >= 400:
                    raise ProviderError(f"Gemini {model}: {_reason(response)}")
                outcome.model = model
                for data in _sse_data(response):
                    chunk = json.loads(data)
                    if (chunk.get("promptFeedback") or {}).get("blockReason"):
                        raise ProviderError(f"Gemini {model} declined the question.")
                    outcome.model = chunk.get("modelVersion") or outcome.model
                    for candidate in chunk.get("candidates") or []:
                        for part in (candidate.get("content") or {}).get("parts") or []:
                            if part.get("text") and not part.get("thought"):
                                yield part["text"]
                        if candidate.get("finishReason") == "MAX_TOKENS":
                            outcome.complete = False
                        grounding = candidate.get("groundingMetadata") or {}
                        for source in grounding.get("groundingChunks") or []:
                            page = source.get("web") or {}
                            if page.get("uri"):
                                outcome.web_sources.append(
                                    {"title": page.get("title") or page["uri"], "url": page["uri"]}
                                )
        except httpx2.HTTPError as error:
            raise ProviderError(f"Gemini {model} could not be reached: {error}") from error


class _SearchRefused(Exception):
    """Google refused the search tool (its quota), before any text was sent."""


class OpenAICompatibleProvider:
    """Groq, OpenRouter, Mistral and the others in services.py: the OpenAI
    chat-completions protocol.

    Groq's "compound" models search the web by themselves.
    """

    def __init__(
        self,
        name: str,
        label: str,
        base_url: str,
        client: httpx2.Client,
        api_key: str | None,
        models: list[str],
        max_tokens: int,
        extra_headers: dict[str, str] | None = None,
    ):
        self.name = name
        self.label = label
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.api_key = api_key
        self.models = models
        self.max_tokens = max_tokens
        self.extra_headers = extra_headers or {}

    def searches(self, model: str) -> bool:
        return "compound" in model

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
        payload: dict = {
            "model": model,
            "messages": [{"role": "system", "content": system}]
            + [{"role": t.role, "content": _openai_content(t)} for t in turns],
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        # Pollinations needs no key.
        auth = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        headers = {**auth, **self.extra_headers}
        try:
            with self.client.stream(
                "POST", f"{self.base_url}/chat/completions", headers=headers, json=payload
            ) as response:
                if response.status_code >= 400:
                    raise ProviderError(f"{self.label} {model}: {_reason(response)}")
                outcome.model = model
                for data in _sse_data(response):
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if chunk.get("error"):
                        raise ProviderError(f"{self.label} {model}: {chunk['error']}")
                    outcome.model = chunk.get("model") or outcome.model
                    for choice in chunk.get("choices") or []:
                        text = (choice.get("delta") or {}).get("content")
                        if text:
                            yield text
                        if choice.get("finish_reason") == "length":
                            outcome.complete = False
        except httpx2.HTTPError as error:
            raise ProviderError(f"{self.label} {model} could not be reached: {error}") from error


def _openai_content(turn: Turn) -> str | list[dict]:
    """Plain text, or text and images as content parts (vision models only; others
    refuse the request and the assistant moves on)."""
    if not turn.images:
        return turn.content
    return [
        *(
            {"type": "image_url", "image_url": {"url": f"data:{i.mime};base64,{i.data}"}}
            for i in turn.images
        ),
        {"type": "text", "text": turn.content},
    ]


def _claude_content(turn: Turn) -> str | list[dict]:
    if not turn.images:
        return turn.content
    return [
        *(
            {"type": "image", "source": {"type": "base64", "media_type": i.mime, "data": i.data}}
            for i in turn.images
        ),
        {"type": "text", "text": turn.content},
    ]


class ClaudeProvider:
    name = "claude"
    label = "Claude"

    def __init__(self, client: anthropic.Anthropic, models: list[str], max_tokens: int):
        self.client = client
        self.models = models
        self.max_tokens = max_tokens

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
        options: dict = {} if temperature is None else {"temperature": min(temperature, 1.0)}
        try:
            with self.client.messages.stream(
                model=model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": t.role, "content": _claude_content(t)} for t in turns],
                **options,
            ) as stream:
                outcome.model = model
                yield from stream.text_stream
                final = stream.get_final_message()
                outcome.model = final.model or model
                outcome.complete = final.stop_reason != "max_tokens"
                if final.stop_reason == "refusal":
                    raise ProviderError(f"Claude {model} declined the question.")
        except anthropic.APIStatusError as error:
            body = error.body
            message = body.get("error", {}).get("message") if isinstance(body, dict) else None
            raise ProviderError(f"Claude {model}: {message or error.message}"[:300]) from error
        except anthropic.APIError as error:
            raise ProviderError(f"Claude {model} could not be reached: {error}") from error
