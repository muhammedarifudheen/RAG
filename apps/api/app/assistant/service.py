"""The assistant: answers any question, from the knowledge base, the web or general knowledge.

It routes each question to the model services that suit it (see router). With a
council (the default), up to a dozen agents on different services answer in
parallel and one model merges their best points into the answer it streams; a
failing agent is replaced by the next model in line, and slow ones are not waited
for. Without one, a single model answers, and the next takes over if it fails.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache

import anthropic
import httpx2
from fastapi import HTTPException

from app.config import settings
from app.schemas import AskResponse, Attachment, ChatTurn, CodeChunk, GeneratedImage, WebSource
from app.services.search import extract_citations

from .horde import HordeTextProvider
from .images import (
    CloudflareImages,
    HordeImages,
    HuggingFaceImages,
    ImageService,
    PollinationsImages,
    gallery,
)
from .prompt import (
    IMAGE_SYSTEM,
    MERGE,
    FollowUpSplitter,
    conversation,
    system_prompt,
    with_drafts,
)
from .providers import (
    ClaudeProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    Outcome,
    Provider,
    ProviderError,
    Turn,
)
from .router import Mode, Route, classify, model_order, provider_order, wants_image
from .services import configured, openrouter_free_models
from .web import WebResult, WebSearch, search_query, web_block

logger = logging.getLogger("atlas.api.assistant")

# (event name, data) pairs, sent to the browser as server-sent events.
Event = tuple[str, dict]


# How a picture answer begins; a short follow-up to one ("make it blue") draws again.
PICTURE_ANSWER = "Here's your picture"
_QUESTION = re.compile(
    r"^\s*(what|why|how|who|when|where|which|is|are|does|do|can|could)\b|\?\s*$", re.IGNORECASE
)


@dataclass(frozen=True)
class Options:
    """What the user chose for this question, besides the question itself."""

    attachments: Sequence[Attachment] = ()
    style: str = "balanced"
    temperature: float | None = None
    instructions: str = ""
    task: str = "answer"  # or "image"


# Services too slow to wait for when a quick reply is all that is needed.
SLOW_SERVICES = ("horde",)
PROMPT_WRITING_SECONDS = 20.0

# How long a model sits out after failing: out of credit (the account needs paying),
# over quota (a per-minute limit), or merely busy (worth one more try soon). A model this
# account cannot use at all (withdrawn, kept for certain apps, or asked for more than its
# plan allows in one go) sits out for hours.
_UNUSABLE = re.compile(
    r"only available on|not found for account|model.?not.?found|does not exist|request too large",
    re.IGNORECASE,
)
_BILLING = re.compile(r"credit|billing|payment|insufficient.?(funds|balance)", re.IGNORECASE)
_QUOTA = re.compile(r"quota|rate.?limit|too many requests|\b429\b", re.IGNORECASE)
# Also the occasional glitch of one reply: a stray tool call, unparsable output.
_BUSY = re.compile(
    r"high demand|overloaded|unavailable|\b50[234]\b|try again|tool_use_failed|"
    r"parsing failed|could not be parsed|provider returned error",
    re.IGNORECASE,
)
UNUSABLE_REST = 6 * 3600.0
BILLING_REST = 1800.0
QUOTA_REST = 60.0
RETRY_PAUSE = 2.0


def rest_after(detail: str) -> float:
    """Seconds a model should sit out after failing with `detail`."""
    if _UNUSABLE.search(detail):
        return UNUSABLE_REST
    # Quota before billing: Gemini's quota message also mentions "billing details".
    if _QUOTA.search(detail):
        return QUOTA_REST
    if _BILLING.search(detail):
        return BILLING_REST
    return 0.0


# Services that cannot see attached images (they would answer without them).
NO_VISION = ("horde", "pollinations")


@dataclass
class Draft:
    """One agent's answer, for the merger."""

    agent: int
    service: str  # the provider's name, and the model it was asked for
    seat: str
    provider: str  # its label, and the model that answered
    model: str
    answer: str
    suggestions: list[str]
    web_sources: list[dict[str, str]]
    seconds: float = 0.0  # how long it took to write


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
        image_url_template: str = "https://image.pollinations.ai/prompt/{prompt}?seed={seed}",
        image_services: Sequence[ImageService] | None = None,
        gallery_size: int = 1,
        image_max_wait: float = 75.0,
        council_size: int = 1,
        council_grace: float = 15.0,
        council_max_wait: float = 60.0,
        web: WebSearch | None = None,
        fast_mergers: Sequence[str] = (),
        merge_by_speed: bool = False,
        merge_drafts: int = 12,
    ) -> None:
        self.providers = {p.name: p for p in providers}
        self.image_services = (
            list(image_services)
            if image_services is not None
            else [PollinationsImages(image_url_template)]
        )
        self.gallery_size = gallery_size
        self.image_max_wait = image_max_wait
        self.council_size = council_size
        self.council_grace = council_grace
        self.council_max_wait = council_max_wait
        self.web = web
        # Services that merge first (the quickest), when one of their models answered.
        self.fast_mergers = tuple(fast_mergers)
        # Then the agents that answered, quickest first (their draft's time predicts it).
        self.merge_by_speed = merge_by_speed
        self.merge_drafts = merge_drafts
        # (service, model) -> when it may be asked again, after running out of quota.
        self.resting: dict[tuple[str, str], float] = {}
        self.clock = time.monotonic
        self.best_order = best_order
        self.models_per_provider = models_per_provider
        self.web_search = web_search
        self.min_score = min_score
        self.image_url_template = image_url_template

    def respond(
        self,
        question: str,
        chunks: Sequence[CodeChunk],
        history: Sequence[ChatTurn] = (),
        mode: Mode = "auto",
        options: Options | None = None,
    ) -> Iterator[Event]:
        """Events: `route`, then `delta` pieces of text (a `reset` drops what came so far
        when a service fails mid-answer and the next one starts over), then `done` with
        the whole response, or `error`."""
        options = options or Options()
        images = any(a.kind == "image" for a in options.attachments)
        if options.task == "image" or (not images and _wants_picture(question, history)):
            yield from self._draw(question, history, mode)
            return
        top = chunks[0].score if chunks else None
        route = classify(question, top, images=images)
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

        found: list[WebResult] = []
        if self.web is not None and route != "chat":
            yield "searching", {}
            previous = next((t.content for t in reversed(history) if t.role == "user"), None)
            started = time.monotonic()
            found = self.web.search(search_query(question, previous), recent=route == "current")
            logger.info("web search: %d results in %.1fs", len(found), time.monotonic() - started)
            yield "web", {"sources": [{"title": r.title, "url": r.url} for r in found[:12]]}
        searched = [{"title": r.title, "url": r.url} for r in found]

        system = system_prompt(style=options.style, instructions=options.instructions)
        tuning = {} if options.temperature is None else {"temperature": options.temperature}
        today = datetime.now(UTC).date()
        turns = conversation(
            question,
            shown,
            history,
            options.attachments,
            web=web_block(found, today) if found else "",
        )
        panel = self._candidates(order, route, images)
        if self.council_size > 1 and len(panel) > 1:
            # The merger needs the web results' links, not their text: a smaller request
            # is quicker and fits free per-minute limits.
            merge_base = conversation(
                question,
                shown,
                history,
                options.attachments,
                web=web_block(found, today, brief=True) if found else "",
            )
            yield from self._council(
                question, route, panel, order, shown, system, turns, tuning, searched, merge_base
            )
            return
        failures: list[str] = []
        for name, model in self._attempts(order, route):
            provider = self.providers[name]
            web = self.web_search and route != "chat" and provider.searches(model)
            outcome = Outcome()
            splitter = FollowUpSplitter()
            started, wrote = time.monotonic(), False
            try:
                for piece in provider.stream(model, system, turns, outcome, web=web, **tuning):
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
                detail = str(error) if isinstance(error, ProviderError) else f"bad reply: {error}"
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
                web_sources=_unique_sources(outcome.web_sources + searched),
            )
            yield "done", response.model_dump()
            return

        last = failures[-1] if failures else "no answer"
        yield "error", {"status": 503, "detail": f"Every AI service failed; the last said: {last}"}

    def _candidates(
        self, order: Sequence[str], route: Route, images: bool
    ) -> list[tuple[str, str]]:
        """Agents for a council, in the order to seat them: each service's best-suited
        model first, taking turns between services so the panel is varied, then each
        service's next models (seated as replacements when an agent fails)."""
        names = [n for n in order if not (images and n in NO_VISION)]
        ranked = {n: model_order(self.providers[n].models, route) for n in names}
        depth = max((len(models) for models in ranked.values()), default=0)
        every = [(n, ranked[n][i]) for i in range(depth) for n in names if i < len(ranked[n])]
        # Models resting after a quota or billing failure wait at the back.
        return [p for p in every if not self._resting(p)] + [p for p in every if self._resting(p)]

    def _resting(self, pair: tuple[str, str]) -> bool:
        return self.resting.get(pair, 0.0) > self.clock()

    def _note_failure(self, pair: tuple[str, str], detail: str) -> None:
        rest = rest_after(detail)
        if rest:
            self.resting[pair] = self.clock() + rest

    def _council(
        self,
        question: str,
        route: Route,
        candidates: list[tuple[str, str]],
        order: Sequence[str],
        shown: Sequence[CodeChunk],
        system: str,
        turns: list[Turn],
        tuning: dict,
        searched: Sequence[dict[str, str]] = (),
        merge_base: list[Turn] | None = None,
    ) -> Iterator[Event]:
        """Seats up to `council_size` agents, collects their drafts, then merges them."""
        results: queue.Queue = queue.Queue()
        seats = candidates[: self.council_size]
        reserve = candidates[self.council_size :]

        def run(agent: int, name: str, model: str, pause: float = 0.0) -> None:
            if pause:
                time.sleep(pause)
            provider = self.providers[name]
            web = self.web_search and route != "chat" and provider.searches(model)
            outcome = Outcome()
            started = time.monotonic()
            try:
                splitter = FollowUpSplitter()
                for piece in provider.stream(model, system, turns, outcome, web=web, **tuning):
                    splitter.feed(piece)
                _, answer, suggestions = splitter.finish()
                if not answer:
                    raise ProviderError(f"{provider.label} {model} returned an empty answer.")
                draft = Draft(
                    agent,
                    name,
                    model,
                    provider.label,
                    outcome.model or model,
                    answer,
                    suggestions,
                    outcome.web_sources,
                    time.monotonic() - started,
                )
                results.put(("done", agent, draft, draft.seconds))
            except (ProviderError, ValueError, KeyError) as error:
                detail = str(error) if isinstance(error, ProviderError) else f"bad reply: {error}"
                results.put(("failed", agent, detail, time.monotonic() - started))
            except Exception as error:  # an agent must never take the council down
                logger.exception("assistant %s %s crashed", name, model)
                results.put(
                    ("failed", agent, f"{type(error).__name__}", time.monotonic() - started)
                )

        def seat(agent: int, name: str, model: str, pause: float = 0.0) -> Event:
            seated[agent] = (name, model)
            threading.Thread(target=run, args=(agent, name, model, pause), daemon=True).start()
            label = self.providers[name].label
            return "agent", {"id": agent, "service": label, "model": model, "state": "thinking"}

        seated: dict[int, tuple[str, str]] = {}
        retried: set[tuple[str, str]] = set()
        for agent, (name, model) in enumerate(seats):
            yield seat(agent, name, model)
        running = set(range(len(seats)))
        next_agent = len(seats)
        drafts: list[Draft] = []
        failures: list[str] = []
        started = time.monotonic()
        enough_at: float | None = None
        while running:
            if enough_at is not None:
                until = min(enough_at + self.council_grace, started + self.council_max_wait)
            elif drafts:
                until = started + self.council_max_wait
            else:
                until = started + max(self.council_max_wait, 90.0)
            try:
                state, agent, detail, seconds = results.get(
                    timeout=max(0.0, until - time.monotonic())
                )
            except queue.Empty:
                break
            running.discard(agent)
            if state == "done":
                drafts.append(detail)
                if len(drafts) >= 2 and enough_at is None:
                    enough_at = time.monotonic()
                yield "agent", {"id": agent, "state": "done", "seconds": round(seconds, 1)}
                continue
            failures.append(detail)
            pair = seated[agent]
            self._note_failure(pair, detail)
            logger.info("assistant agent %d failed in %.1fs (%s)", agent, seconds, detail)
            yield "agent", {"id": agent, "state": "failed", "seconds": round(seconds, 1)}
            # A model that was only busy gets one more try, after the untried ones.
            if _BUSY.search(detail) and pair not in retried:
                retried.add(pair)
                reserve.append(pair)
            if reserve:
                name, model = reserve.pop(0)
                pause = RETRY_PAUSE if (name, model) in retried else 0.0
                yield seat(next_agent, name, model, pause)
                running.add(next_agent)
                next_agent += 1
        for agent in sorted(running):
            yield "agent", {"id": agent, "state": "skipped"}

        if not drafts:
            last = failures[-1] if failures else "no answer in time"
            yield (
                "error",
                {"status": 503, "detail": f"Every AI service failed; the last said: {last}"},
            )
            return
        drafts.sort(key=lambda d: d.agent)  # the best-suited agents first
        sources = [source for d in drafts for source in d.web_sources] + list(searched)
        if len(drafts) == 1:
            only = drafts[0]
            yield "delta", {"text": only.answer}
            yield (
                "done",
                self._response(
                    question,
                    only.answer,
                    shown,
                    only.model,
                    True,
                    only.provider,
                    route,
                    only.suggestions,
                    sources,
                    drafts,
                ).model_dump(),
            )
            return

        yield "merging", {"drafts": len(drafts)}
        merge_turns = with_drafts(
            merge_base or turns, [d.answer for d in drafts[: self.merge_drafts]]
        )
        merge_system = f"{system}\n\n{MERGE}"
        merge_order = _merge_order(drafts, order, self._attempts(order, route), self._resting)
        # The quickest services merge first: the merged answer is what the user waits for.
        answered = {(d.service, d.seat) for d in drafts}
        fast = [p for f in self.fast_mergers for p in merge_order if p[0] == f and p in answered]
        if self.merge_by_speed:
            quickest = sorted(
                (d for d in drafts if d.service not in SLOW_SERVICES), key=lambda d: d.seconds
            )
            fast += [(d.service, d.seat) for d in quickest if (d.service, d.seat) not in fast]
        merge_order = fast + [p for p in merge_order if p not in fast]
        for name, model in merge_order:
            provider = self.providers[name]
            outcome = Outcome()
            splitter = FollowUpSplitter()
            wrote = False
            started = time.monotonic()
            try:
                for piece in provider.stream(
                    model, merge_system, merge_turns, outcome, web=False, **tuning
                ):
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
                logger.info("assistant merge %s %s failed (%s)", name, model, error)
                if wrote:
                    yield "reset", {"provider": provider.label}
                continue
            logger.info(
                "assistant merged %d drafts with %s %s in %.1fs",
                len(drafts),
                name,
                model,
                time.monotonic() - started,
            )
            yield (
                "done",
                self._response(
                    question,
                    answer,
                    shown,
                    outcome.model or model,
                    outcome.complete,
                    "Atlas council",
                    route,
                    suggestions or drafts[0].suggestions,
                    sources + outcome.web_sources,
                    drafts,
                ).model_dump(),
            )
            return

        # No model could merge: the best-suited agent's draft stands.
        best = drafts[0]
        yield "delta", {"text": best.answer}
        yield (
            "done",
            self._response(
                question,
                best.answer,
                shown,
                best.model,
                True,
                best.provider,
                route,
                best.suggestions,
                sources,
                drafts,
            ).model_dump(),
        )

    def _response(
        self,
        question: str,
        answer: str,
        shown: Sequence[CodeChunk],
        model: str,
        complete: bool,
        provider: str,
        route: Route,
        suggestions: list[str],
        sources: list[dict[str, str]],
        drafts: Sequence[Draft],
    ) -> AskResponse:
        return AskResponse(
            question=question,
            answer=answer,
            citations=extract_citations(answer, list(shown)),
            chunks=list(shown),
            model=model,
            complete=complete,
            provider=provider,
            route=route,
            suggestions=suggestions,
            web_sources=_unique_sources(sources),
            agents=[f"{d.provider} · {d.model}" for d in drafts],
        )

    def _attempts(self, order: Sequence[str], route: Route) -> list[tuple[str, str]]:
        """(service, model) pairs in the order to try them: each service's best-suited
        models first, then, if all of those fail, the rest of every service's models.
        Free quotas are per model, so a model not yet tried may still answer."""
        ranked = {name: model_order(self.providers[name].models, route) for name in order}
        first = [(n, m) for n in order for m in ranked[n][: self.models_per_provider]]
        rest = [(n, m) for n in order for m in ranked[n][self.models_per_provider :]]
        return first + rest

    def _draw(self, question: str, history: Sequence[ChatTurn], mode: Mode) -> Iterator[Event]:
        """A picture: a fast model turns the request into a detailed prompt, and the image
        service draws it. Without a working model the request itself is the prompt."""
        route: Route = "image"
        order = provider_order(mode, route, self.best_order, set(self.providers))
        yield "route", {"route": route, "mode": mode, "providers": order}
        prompt, provider_label, model_name = _bare_request(question), None, "flux"
        turns = conversation(question, [], history)
        # Quick models only, and not for long: the request's own words will do.
        give_up = time.monotonic() + PROMPT_WRITING_SECONDS
        for name, model in self._attempts(order, route):
            if name in SLOW_SERVICES:
                continue
            if time.monotonic() > give_up:
                break
            provider = self.providers[name]
            outcome = Outcome()
            try:
                written = "".join(
                    provider.stream(model, IMAGE_SYSTEM, turns, outcome, web=False)
                ).strip()
            except (ProviderError, ValueError, KeyError) as error:
                logger.info("assistant %s %s: no image prompt (%s)", name, model, error)
                continue
            if written:
                prompt = written.strip('"').strip()[:800]
                provider_label = provider.label
                break
        answer = f"{PICTURE_ANSWER}, drawn from this description:\n\n> {prompt}"
        yield "delta", {"text": answer}
        drawn = []
        for picture in gallery(self.image_services, prompt, self.gallery_size, self.image_max_wait):
            drawn.append(GeneratedImage(url=picture.url, prompt=prompt, service=picture.service))
            yield "image", drawn[-1].model_dump()
        if not drawn:
            yield "error", {"status": 503, "detail": "No image service could draw this picture."}
            return
        response = AskResponse(
            question=question,
            answer=answer,
            citations=[],
            chunks=[],
            model=model_name,
            complete=True,
            provider=provider_label or "Pollinations",
            route=route,
            suggestions=[
                "Draw another version",
                "Draw it as a watercolour painting",
                "Draw it at night",
            ],
            images=drawn,
        )
        yield "done", response.model_dump()

    def answer(
        self,
        question: str,
        chunks: Sequence[CodeChunk],
        history: Sequence[ChatTurn] = (),
        mode: Mode = "auto",
        options: Options | None = None,
    ) -> AskResponse:
        """The same as `respond`, collected into one response."""
        for name, data in self.respond(question, chunks, history, mode, options):
            if name == "done":
                return AskResponse(**data)
            if name == "error":
                raise AssistantError(data["status"], data["detail"])
        raise AssistantError(503, "The assistant produced no answer.")


_REQUEST = re.compile(
    r"^\s*(please\s+|can you\s+|could you\s+)?"
    r"(draw|paint|sketch|illustrate|generate|create|make|design|render|produce)\s+(me\s+)?"
    r"((an?|the|some)\s+)?((image|picture|photo|drawing|illustration|painting)\s+(of\s+)?)?",
    re.IGNORECASE,
)


def _bare_request(question: str) -> str:
    """The description in a request to draw: "draw a fox" becomes "a fox"."""
    bare = _REQUEST.sub("", question.strip(), count=1).strip().rstrip("?.!")
    return bare or question.strip()


def _merge_order(
    drafts: Sequence[Draft],
    order: Sequence[str],
    attempts: Sequence[tuple[str, str]],
    resting: Callable[[tuple[str, str]], bool] = lambda _: False,
) -> list[tuple[str, str]]:
    """Who merges: the models that just answered (so known to be working), the
    strongest service first, then everything else in the usual order."""
    rank = {name: i for i, name in enumerate(order)}
    ranked = sorted(drafts, key=lambda d: (rank.get(d.service, len(rank)), d.agent))
    answered = [(d.service, d.seat) for d in ranked]
    rest = [pair for pair in attempts if pair not in answered]
    return answered + [p for p in rest if not resting(p)] + [p for p in rest if resting(p)]


def _wants_picture(question: str, history: Sequence[ChatTurn]) -> bool:
    """A request to draw, or a short change to the picture just drawn ("make it blue")."""
    if wants_image(question):
        return True
    last = next((t for t in reversed(history) if t.role == "assistant"), None)
    return (
        last is not None
        and last.content.startswith(PICTURE_ANSWER)
        and len(question) < 200
        and not _QUESTION.search(question)
    )


def _unique_sources(sources: list[dict[str, str]]) -> list[WebSource]:
    seen: dict[str, WebSource] = {}
    for source in sources:
        seen.setdefault(source["url"], WebSource(title=source["title"], url=source["url"]))
    return list(seen.values())[:12]


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
    if settings.anthropic_api_key:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120.0)
        providers.append(ClaudeProvider(client, [settings.anthropic_model], limit))

    def models_of(setting: str) -> list[str]:
        if setting == "openrouter_models" and getattr(settings, setting).strip() == "auto":
            return openrouter_free_models(http)
        return _models(setting)

    for service, key, base, models in configured(lambda name: getattr(settings, name), models_of):
        providers.append(
            OpenAICompatibleProvider(
                service.name,
                service.label,
                base,
                http,
                key,
                models,
                limit,
                extra_headers=service.extra_headers,
            )
        )
    if settings.horde_enabled:
        providers.append(
            HordeTextProvider(http, settings.horde_api_key, _models("horde_text_models"))
        )

    images: list[ImageService] = []
    if settings.cloudflare_account_id and settings.cloudflare_api_token:
        images.append(
            CloudflareImages(
                http,
                settings.cloudflare_account_id,
                settings.cloudflare_api_token,
                settings.cloudflare_image_model,
            )
        )
    if settings.huggingface_api_key:
        images.append(
            HuggingFaceImages(http, settings.huggingface_api_key, settings.huggingface_image_model)
        )
    if settings.horde_enabled:
        images.append(HordeImages(http, settings.horde_api_key, _models("horde_image_models")))
    images.append(PollinationsImages(settings.image_url_template))

    logger.info(
        "assistant services: %s; image services: %s",
        ", ".join(f"{p.name} ({len(p.models)})" for p in providers) or "none",
        ", ".join(i.label for i in images),
    )
    return Assistant(
        providers,
        best_order=settings.assistant_best_order,
        models_per_provider=settings.assistant_models_per_provider,
        web_search=settings.assistant_web_search,
        min_score=settings.assistant_min_score,
        image_services=images,
        gallery_size=settings.image_gallery_size,
        image_max_wait=settings.image_max_wait,
        council_size=settings.assistant_council_size,
        council_grace=settings.assistant_council_grace,
        council_max_wait=settings.assistant_council_max_wait,
        web=WebSearch(
            http,
            tavily_key=settings.tavily_api_key,
            brave_key=settings.brave_api_key,
            news=settings.web_news,
            wikipedia=settings.web_wikipedia,
            max_wait=settings.web_max_wait,
        )
        if settings.assistant_web_search
        else None,
        fast_mergers=[n.strip() for n in settings.assistant_fast_mergers.split(",") if n.strip()],
        merge_by_speed=settings.assistant_merge_by_speed,
        merge_drafts=settings.assistant_merge_drafts,
    )


def get_assistant() -> Assistant:
    assistant = _build()
    if not assistant.providers:
        raise HTTPException(503, "No AI service is configured; set GEMINI_API_KEY or another key.")
    return assistant
