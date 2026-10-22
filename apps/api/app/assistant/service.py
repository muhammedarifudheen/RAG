"""The assistant: answers any question, from the knowledge base, the web or general knowledge.

It routes each question to the model services that suit it (see router), streams
the answer as it is written, and moves on to the next service or model when one
is overloaded, out of quota or failing.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Sequence
from functools import cache

import anthropic
import httpx2
from fastapi import HTTPException

from app.config import settings
from app.schemas import AskResponse, ChatTurn, CodeChunk, WebSource
from app.services.search import extract_citations

from .prompt import FollowUpSplitter, conversation, system_prompt
from .providers import (
    ClaudeProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    Outcome,
    Provider,
    ProviderError,
)
from .router import Mode, classify, model_order, provider_order

logger = logging.getLogger("atlas.api.assistant")

# (event name, data) pairs, sent to the browser as server-sent events.
Event = tuple[str, dict]


class AssistantError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class Assistant:
    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        best_order: str = "claude,gemini,openrouter,mistral,groq",
        models_per_provider: int = 2,
        web_search: bool = True,
        min_score: float = 0.3,
    ) -> None:
        self.providers = {p.name: p for p in providers}
        self.best_order = best_order
        self.models_per_provider = models_per_provider
        self.web_search = web_search
        self.min_score = min_score

    def respond(
        self,
        question: str,
        chunks: Sequence[CodeChunk],
        history: Sequence[ChatTurn] = (),
        mode: Mode = "auto",
    ) -> Iterator[Event]:
        """Events: `route`, then `delta` pieces of text (a `reset` drops what came so far
        when a service fails mid-answer and the next one starts over), then `done` with
        the whole response, or `error`."""
        top = chunks[0].score if chunks else None
        route = classify(question, top)
        shown = [c for c in chunks if c.score >= self.min_score]
        order = provider_order(mode, route, self.best_order, set(self.providers))
        if route == "current":
            # Recent events need a web search: services that can search right now first.
            order.sort(
                key=lambda n: not any(map(self.providers[n].searches, self.providers[n].models))
            )
        yield "route", {"route": route, "mode": mode, "providers": order}
        if not order:
            yield "error", {"status": 503, "detail": "No AI service is configured; add an API key."}
            return

        system = system_prompt()
        turns = conversation(question, shown, history)
        failures: list[str] = []
        for name in order:
            provider = self.providers[name]
            for model in model_order(provider.models, route)[: self.models_per_provider]:
                web = self.web_search and route != "chat" and provider.searches(model)
                outcome = Outcome()
                splitter = FollowUpSplitter()
                started, wrote = time.monotonic(), False
                try:
                    for piece in provider.stream(model, system, turns, outcome, web=web):
                        text = splitter.feed(piece)
                        if text:
                            wrote = True
                            yield "delta", {"text": text}
                    rest, answer, suggestions = splitter.finish()
                    if not answer:
                        raise ProviderError(f"{provider.label} {model} returned an empty answer.")
                    if rest:
                        yield "delta", {"text": rest}
                except (ProviderError, ValueError, KeyError) as error:
                    detail = (
                        str(error) if isinstance(error, ProviderError) else f"bad reply: {error}"
                    )
                    logger.info(
                        "assistant %s %s: failed in %.1fs (%s)",
                        name,
                        model,
                        time.monotonic() - started,
                        detail,
                    )
                    failures.append(detail)
                    if wrote:
                        yield "reset", {"provider": provider.label}
                    continue
                logger.info(
                    "assistant %s %s: answered %s in %.1fs",
                    name,
                    model,
                    route,
                    time.monotonic() - started,
                )
                response = AskResponse(
                    question=question,
                    answer=answer,
                    citations=extract_citations(answer, list(shown)),
                    chunks=list(shown),
                    model=outcome.model or model,
                    complete=outcome.complete,
                    provider=provider.label,
                    route=route,
                    suggestions=suggestions,
                    web_sources=_unique_sources(outcome.web_sources),
                )
                yield "done", response.model_dump()
                return

        last = failures[-1] if failures else "no answer"
        yield "error", {"status": 503, "detail": f"Every AI service failed; the last said: {last}"}

    def answer(
        self,
        question: str,
        chunks: Sequence[CodeChunk],
        history: Sequence[ChatTurn] = (),
        mode: Mode = "auto",
    ) -> AskResponse:
        """The same as `respond`, collected into one response."""
        for name, data in self.respond(question, chunks, history, mode):
            if name == "done":
                return AskResponse(**data)
            if name == "error":
                raise AssistantError(data["status"], data["detail"])
        raise AssistantError(503, "The assistant produced no answer.")


def _unique_sources(sources: list[dict[str, str]]) -> list[WebSource]:
    seen: dict[str, WebSource] = {}
    for source in sources:
        seen.setdefault(source["url"], WebSource(title=source["title"], url=source["url"]))
    return list(seen.values())[:8]


def _models(setting: str) -> list[str]:
    """A comma-separated model list from settings; blank (as docker-compose passes an
    unset variable) means the default list."""
    value = getattr(settings, setting) or ""
    models = [m.strip() for m in value.split(",") if m.strip()]
    return models or _models_default(setting)


def _models_default(setting: str) -> list[str]:
    default = type(settings).model_fields[setting].default
    return [m.strip() for m in default.split(",") if m.strip()]


@cache
def _build() -> Assistant:
    http = httpx2.Client(timeout=httpx2.Timeout(120.0, connect=10.0))
    limit = settings.assistant_max_tokens
    providers: list[Provider] = []
    if settings.gemini_api_key:
        providers.append(
            GeminiProvider(http, settings.gemini_api_key, _models("gemini_models"), limit)
        )
    if settings.groq_api_key:
        providers.append(
            OpenAICompatibleProvider(
                "groq",
                "Groq",
                "https://api.groq.com/openai/v1",
                http,
                settings.groq_api_key,
                _models("groq_models"),
                limit,
            )
        )
    if settings.openrouter_api_key:
        providers.append(
            OpenAICompatibleProvider(
                "openrouter",
                "OpenRouter",
                "https://openrouter.ai/api/v1",
                http,
                settings.openrouter_api_key,
                _models("openrouter_models"),
                limit,
                extra_headers={"X-Title": "Atlas"},
            )
        )
    if settings.mistral_api_key:
        providers.append(
            OpenAICompatibleProvider(
                "mistral",
                "Mistral",
                "https://api.mistral.ai/v1",
                http,
                settings.mistral_api_key,
                _models("mistral_models"),
                limit,
            )
        )
    if settings.anthropic_api_key:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120.0)
        providers.append(ClaudeProvider(client, [settings.anthropic_model], limit))
    return Assistant(
        providers,
        best_order=settings.assistant_best_order,
        models_per_provider=settings.assistant_models_per_provider,
        web_search=settings.assistant_web_search,
        min_score=settings.assistant_min_score,
    )


def get_assistant() -> Assistant:
    assistant = _build()
    if not assistant.providers:
        raise HTTPException(503, "No AI service is configured; set GEMINI_API_KEY or another key.")
    return assistant
