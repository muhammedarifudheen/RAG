"""The assistant: answers any question, from the knowledge base, the web or general knowledge.

It routes each question to the model services that suit it (see router). With a
council (the default), up to a dozen agents on different services answer in
parallel and one model merges their best points into the answer it streams; a
failing agent is replaced by the next model in line, and slow ones are not waited
for. Without one, a single model answers, and the next takes over if it fails.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from typing import TypeVar

import anthropic
import httpx2
from fastapi import HTTPException

from app.analysis.repo import RepoReport, RepoTooLarge, analyse_repo, summary_for_agents
from app.analysis.review import code_files, files_summary, repo_url, to_schema, wants_review
from app.analysis.static import analyse_files
from app.config import settings
from app.schemas import (
    AgentDraft,
    AskResponse,
    Attachment,
    ChatTurn,
    Citation,
    CodeChunk,
    FactCheck,
    GeneratedImage,
    Reranking,
    WebSource,
)
from app.services.search import extract_citations, tidy_citations

from .agent import (
    MAX_TOOL_CALLS,
    ResearchTools,
    hits_text,
    notes_block,
    parse_action,
    read_text,
)
from .cache import TTLCache, key_of
from .confidence import confidence
from .factcheck import parse_fact_check
from .horde import HordeTextProvider
from .images import (
    CloudflareImages,
    GeminiImages,
    HordeImages,
    HuggingFaceImages,
    ImageService,
    PollinationsImages,
    TogetherImages,
    gallery,
)
from .planner import parse_queries
from .prompt import (
    FORMATS,
    IMAGE_SYSTEM,
    MERGE,
    NOT_IN_SOURCES,
    QUERY_PLANNER,
    RESEARCH_PROTOCOL,
    REVIEW,
    FollowUpSplitter,
    audit_prompt,
    context_blocks,
    conversation,
    fact_check_prompt,
    gap_prompt,
    judge_prompt,
    rank_prompt,
    research_prompt,
    strict_prompt,
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
from .rerank import PASSAGE_CHARS, chunk_text, parse_judgement, parse_ranking
from .router import (
    Mode,
    Route,
    classify,
    model_order,
    provider_order,
    wants_code_answer,
    wants_image,
)
from .services import configured, openrouter_free_models
from .web import WebResult, WebSearch, search_query, web_block

logger = logging.getLogger("atlas.api.assistant")
T = TypeVar("T")

# A repository is cloned and analysed one at a time (memory), and given this long.
_REPO_ANALYSIS = threading.Lock()
REPO_ANALYSIS_SECONDS = 300.0

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
    task: str = "answer"  # or "image", "review"
    services: Sequence[str] = ()  # only these answer; empty is all
    council_size: int | None = None
    merger: str | None = None
    min_score: float | None = None
    web_search: bool = True
    max_tokens: int | None = None
    format: str = "markdown"  # or "plain", "json"
    include_drafts: bool = False
    strict: bool = False  # sources only, with the user's strict rules
    search_queries: Sequence[str] = ()  # what the query planner had searched for
    reranking: Reranking | None = None  # what the relevance judge did
    research: ResearchTools | None = None  # deep research: the agent's tools
    timings: dict | None = None  # seconds per stage before the answer: plan, search, judge
    notice: str | None = None  # something to tell the user, such as a search fallback


# The query planner's time; after it the question alone is searched.
PLAN_SECONDS = 5.0
# The relevance judge's time for all the excerpts, and how many models share them.
JUDGE_SECONDS = 6.0
JUDGE_MODELS = 8
# The listwise ranker's time; after it the judge's order stands.
RANK_SECONDS = 8.0
# The fact-checker's time for one answer.
FACT_CHECK_SECONDS = 30.0
# The gap finder's and the knowledge-base audit's time.
GAP_SECONDS = 40.0
AUDIT_SECONDS = 120.0
# Deep research: the agent's time for all its tool calls, and the excerpts kept from it.
RESEARCH_SECONDS = 75.0
RESEARCH_EXCERPTS = 16

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
        planner: bool = False,
        reranker: bool = False,
        judge_services: Sequence[str] = (),
        answer_cache: bool = False,
        analyse_repo: Callable[[str, Callable[[str], None]], RepoReport] = analyse_repo,
        fetch_text: Callable[[str], str] | None = None,
    ) -> None:
        self.providers = {p.name: p for p in providers}
        # Plan several knowledge-base searches per question (see plan_queries).
        self.planner = planner
        # Judge each excerpt's relevance and rerank them (see judge_chunks).
        self.reranker = reranker
        self.judge_services = tuple(judge_services)
        # Answers to repeated questions (the router asks it), and the judge's verdicts per
        # question and excerpt, each for a day.
        self.answer_cache: TTLCache[dict] | None = TTLCache(256) if answer_cache else None
        self.verdict_cache: TTLCache[tuple[int, str]] = TTLCache(5000)
        self.analyse_repo = analyse_repo
        # Reads a GitHub file linked in a review request; None leaves such links out.
        self.fetch_text = fetch_text
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
        the whole response, or `error`. A code review first sends `analysing` progress and
        the code analyser's `analysis`, which the `done` response carries too."""
        review: dict = {}
        planned = list((options.search_queries if options else ()) or ())
        if planned:
            yield "planned", {"queries": planned}
        reranking = options.reranking if options else None
        if reranking is not None:
            yield "judged", reranking.model_dump()
        notice = options.notice if options else None
        if notice:
            yield "notice", {"message": notice}
        timings = dict((options.timings if options else None) or {})
        answering = time.monotonic()
        steps: list[dict] = []
        for name, data in self._respond(question, chunks, history, mode, options, review):
            if name == "researching":
                steps.append(data)
            if name == "done" and steps:
                data = {**data, "research_steps": steps}
            if name == "done" and review.get("schema") is not None:
                data = {**data, "analysis": review["schema"].model_dump()}
            if name == "done" and planned:
                data = {**data, "search_queries": planned}
            if name == "done" and reranking is not None:
                data = {**data, "reranking": reranking.model_dump()}
            if name == "done":
                timings["answer"] = round(time.monotonic() - answering, 2)
                data = {**data, "timings": timings, "notice": notice}
                shown = [CodeChunk(**c) for c in data.get("chunks", [])]
                rated = confidence(
                    data.get("answer", ""),
                    shown,
                    [Citation(**c) for c in data.get("citations", [])],
                )
                if rated is not None:
                    data = {**data, "confidence": rated.model_dump()}
                _log_answer(question, options, data)
            if (
                name == "done"
                and options is not None
                and options.strict
                and not review
                and data.get("chunks")
                and data.get("answer", "").strip() != NOT_IN_SOURCES
            ):
                # A check takes a reasoning model 15-30 s: the page asks for it (task
                # "check") once the answer is shown, rather than holding the answer back.
                data = {**data, "fact_check_pending": True}
            yield name, data

    def fact_check(
        self,
        question: str,
        answer: str,
        chunks: Sequence[CodeChunk],
        attachments: Sequence[Attachment] = (),
    ) -> FactCheck | None:
        """The fact-checker's report on `answer`, against the excerpts and files it was
        given: the first readable one of two of the judge's services, asked at once (within
        FACT_CHECK_SECONDS). None if neither checked it."""
        context = context_blocks(chunks, attachments) or "(no passages)"
        found = self._race(
            "You check answers against their sources. Reply with the JSON asked for and "
            "nothing else.",
            fact_check_prompt(question[:4000], answer[:20000], context),
            parse_fact_check,
            FACT_CHECK_SECONDS,
            max_tokens=2500,
        )
        if found is None:
            return None
        check, label = found
        return check.model_copy(update={"checked_by": label})

    def find_gaps(self, question: str, catalog: str) -> tuple[str, str] | None:
        """The gap finder's report (markdown) on what the knowledge base, described by
        `catalog`, covers and lacks for `question`, and who wrote it. None if no model
        answered within GAP_SECONDS."""
        return self._race(
            "You review a knowledge base for a retrieval system. Answer in Markdown, under "
            "the three numbered headings asked for; give the source to add as a link when "
            "there is one.",
            gap_prompt(question[:4000], catalog or "(the knowledge base is empty)"),
            lambda text: text.strip() or None,
            GAP_SECONDS,
            max_tokens=2500,
        )

    def audit_sources(self, catalog: str) -> tuple[str, str] | None:
        """The health check's markdown table for the sources in `catalog`, and who wrote
        it. None if no model answered within AUDIT_SECONDS."""
        return self._race(
            "You audit knowledge bases. Reply with the Markdown table asked for and nothing "
            "before it.",
            audit_prompt(catalog),
            lambda text: text.strip() if "|" in text else None,
            AUDIT_SECONDS,
            max_tokens=6000,
        )

    def _race(
        self,
        system: str,
        prompt: str,
        parse: Callable[[str], T | None],
        seconds: float,
        *,
        max_tokens: int,
        racers: int = 2,
    ) -> tuple[T, str] | None:
        """One prompt asked of `racers` of the judge's services at once: the first reply
        `parse` accepts, with "Service · model"; None if none within `seconds`."""
        candidates = [p for p in self._judges() if not self._resting(p)][:racers]
        replies: queue.Queue = queue.Queue()

        def run(name: str, model: str) -> None:
            provider = self.providers[name]
            try:
                reply = "".join(
                    provider.stream(
                        model,
                        system,
                        [Turn("user", prompt)],
                        Outcome(),
                        web=False,
                        max_tokens=max_tokens,
                    )
                )
            except (ProviderError, ValueError, KeyError) as error:
                self._note_failure((name, model), str(error))
                replies.put(None)
                return
            parsed = parse(reply)
            replies.put(None if parsed is None else (parsed, f"{provider.label} · {model}"))

        for name, model in candidates:
            threading.Thread(target=run, args=(name, model), daemon=True).start()
        give_up = time.monotonic() + seconds
        for _ in candidates:
            try:
                found = replies.get(timeout=max(0.0, give_up - time.monotonic()))
            except queue.Empty:
                break
            if found is not None:
                return found
        logger.info("no reply within %.0fs to: %s", seconds, system[:60])
        return None

    def plan_queries(self, question: str) -> list[str]:
        """Up to five knowledge-base searches for `question`: itself, then the query
        planner's (a fast model, given PLAN_SECONDS). Just the question if none answers."""
        order = provider_order("auto", "image", self.best_order, set(self.providers))
        candidates = [
            (n, m)
            for n, m in self._attempts(order, "image")
            if n not in (*SLOW_SERVICES, "pollinations")
        ]
        replies: queue.Queue = queue.Queue()

        def run() -> None:
            for name, model in candidates[:3]:
                try:
                    text = "".join(
                        self.providers[name].stream(
                            model, QUERY_PLANNER, [Turn("user", question)], Outcome(), web=False
                        )
                    )
                except (ProviderError, ValueError, KeyError) as error:
                    logger.info("query planner %s %s failed (%s)", name, model, error)
                    continue
                if "{" in text:
                    replies.put(text)
                    return
            replies.put("")

        threading.Thread(target=run, daemon=True).start()
        try:
            reply = replies.get(timeout=PLAN_SECONDS)
        except queue.Empty:
            logger.info("query planner: no plan within %.0fs", PLAN_SECONDS)
            reply = ""
        return parse_queries(reply, question)

    def _judges(self) -> list[tuple[str, str]]:
        """(service, model) pairs for the relevance judge and the ranker: the judge
        services in their order, so the many small calls spend other quotas than the
        answers' (never Claude, which is paid, nor the slow keyless services)."""
        excluded = (*SLOW_SERVICES, "pollinations", "claude")
        names = [n for n in self.judge_services if n in self.providers]
        names += [n for n in self.providers if n not in names]
        return [
            (n, m)
            for n in names
            if n not in excluded
            for m in self.providers[n].models[: self.models_per_provider]
        ]

    def _research(self, question: str, tools: ResearchTools, out: dict) -> Iterator[Event]:
        """The user's research loop: a model of the judge's services (quick, and not the
        answers' quotas) calls search, read and note, one at a time, up to MAX_TOOL_CALLS
        within RESEARCH_SECONDS, each step sent as a `researching` event. `out` gets the
        excerpts it found and read, and its notes."""
        models = [p for p in self._judges() if not self._resting(p)]
        turns = [Turn("user", research_prompt(question[:4000]))]
        gathered: dict[int, CodeChunk] = {}
        notes: list[str] = []
        calls, unreadable, current = 0, 0, 0
        give_up = time.monotonic() + RESEARCH_SECONDS
        while calls < MAX_TOOL_CALLS and current < len(models) and time.monotonic() < give_up:
            name, model = models[current]
            try:
                reply = "".join(
                    self.providers[name].stream(
                        model, RESEARCH_PROTOCOL, turns, Outcome(), web=False, max_tokens=1500
                    )
                )
            except (ProviderError, ValueError, KeyError) as error:
                self._note_failure((name, model), str(error))
                logger.info("research agent %s %s failed (%s)", name, model, error)
                current += 1
                continue
            action = parse_action(reply)
            if action is None:
                unreadable += 1
                if unreadable >= 2:
                    break
                turns += [
                    Turn("assistant", reply[:2000]),
                    Turn("user", "Reply with one tool call as a JSON object, and nothing else."),
                ]
                continue
            if action.tool == "done":
                break
            calls += 1
            if action.tool == "search":
                hits = tools.search(action.query)
                for hit in hits[:3]:
                    gathered.setdefault(hit.symbol_id, hit)
                result = hits_text(hits)
                summary = f"{len(hits)} results"
            elif action.tool == "read":
                span = tools.read(action.path, action.start, action.end)
                if span is not None:
                    gathered[span.symbol_id] = span
                result = read_text(span)
                summary = "read" if span else "nothing there"
            else:
                notes.append(action.text)
                result, summary = "Saved.", "saved"
            yield (
                "researching",
                {
                    "step": calls,
                    "tool": action.tool,
                    "input": action.described()[:300],
                    "result": summary,
                },
            )
            if calls == MAX_TOOL_CALLS - 1 and not notes:
                # The answer is written from the notes: make sure there are some.
                result += "\n\nOne tool call left: save your findings with note()."
            turns += [
                Turn("assistant", reply.strip()[:2000]),
                Turn("user", f"Result of {action.tool}:\n{result}"),
            ]
        # Reads first: they are the spans the agent chose.
        reads = [c for c in gathered.values() if c.symbol_id < 0]
        out["chunks"] = [*reads, *(c for c in gathered.values() if c.symbol_id >= 0)]
        out["notes"] = notes
        logger.info("research agent: %d tool calls, %d notes", calls, len(notes))

    def judge_chunks(
        self, question: str, chunks: Sequence[CodeChunk]
    ) -> dict[int, tuple[int, str]]:
        """symbol_id -> (score 0-10, reason) from the relevance judge: one call per excerpt,
        all at once, spread over the fast models (another one if a call fails). Excerpts not
        judged within JUDGE_SECONDS are left out of the result."""
        candidates = self._judges()
        models = ([p for p in candidates if not self._resting(p)] or candidates)[:JUDGE_MODELS]
        if not models or not chunks:
            return {}
        lock = threading.Lock()
        system = "You are a relevance judge. Reply with the JSON asked for and nothing else."
        asked = " ".join(question.lower().split())

        def cache_key(chunk: CodeChunk) -> str:
            return key_of(asked, chunk.file, chunk.start_line, chunk.snippet)

        # Excerpts judged for this question before keep their verdicts.
        verdicts: dict[int, tuple[int, str]] = {}
        for chunk in chunks:
            known = self.verdict_cache.get(cache_key(chunk))
            if known is not None:
                verdicts[chunk.symbol_id] = known
        unjudged = [c for c in chunks if c.symbol_id not in verdicts]

        def judge(index: int, chunk: CodeChunk) -> None:
            prompt = judge_prompt(question[:2000], chunk_text(chunk))
            for attempt in range(min(2, len(models))):
                name, model = models[(index + attempt) % len(models)]
                try:
                    reply = "".join(
                        self.providers[name].stream(
                            model,
                            system,
                            [Turn("user", prompt)],
                            Outcome(),
                            web=False,
                            # Room for a reasoning model to think before its JSON.
                            max_tokens=800,
                        )
                    )
                except (ProviderError, ValueError, KeyError) as error:
                    self._note_failure((name, model), str(error))
                    continue
                verdict = parse_judgement(reply)
                if verdict is not None:
                    with lock:
                        verdicts[chunk.symbol_id] = verdict
                    self.verdict_cache.put(cache_key(chunk), verdict)
                    return

        threads = [
            threading.Thread(target=judge, args=(i, c), daemon=True) for i, c in enumerate(unjudged)
        ]
        for thread in threads:
            thread.start()
        give_up = time.monotonic() + JUDGE_SECONDS
        for thread in threads:
            thread.join(max(0.0, give_up - time.monotonic()))
        with lock:
            judged = dict(verdicts)
        logger.info("relevance judge: %d of %d excerpts judged", len(judged), len(chunks))
        return judged

    def rank_chunks(
        self, question: str, chunks: Sequence[CodeChunk]
    ) -> tuple[list[int], str] | None:
        """The listwise ranker's order for `chunks` (0-based, best first) and its reason for
        the top pick: one call with every excerpt, on a fast model (up to three tried,
        within RANK_SECONDS). None if none ranked them."""
        if len(chunks) < 2:
            return None
        candidates = [p for p in self._judges() if not self._resting(p)]
        prompt = rank_prompt(question[:2000], [chunk_text(c, PASSAGE_CHARS) for c in chunks])
        replies: queue.Queue = queue.Queue()

        def run() -> None:
            for name, model in candidates[:3]:
                try:
                    reply = "".join(
                        self.providers[name].stream(
                            model,
                            "You rank passages for a retrieval system. Reply with the JSON "
                            "asked for and nothing else.",
                            [Turn("user", prompt)],
                            Outcome(),
                            web=False,
                            max_tokens=1500,
                        )
                    )
                except (ProviderError, ValueError, KeyError) as error:
                    self._note_failure((name, model), str(error))
                    continue
                ranking = parse_ranking(reply, len(chunks))
                if ranking is not None:
                    replies.put(ranking)
                    return
            replies.put(None)

        threading.Thread(target=run, daemon=True).start()
        try:
            return replies.get(timeout=RANK_SECONDS)
        except queue.Empty:
            logger.info("listwise ranker: no ranking within %.0fs", RANK_SECONDS)
            return None

    def _respond(
        self,
        question: str,
        chunks: Sequence[CodeChunk],
        history: Sequence[ChatTurn],
        mode: Mode,
        options: Options | None,
        review: dict,
    ) -> Iterator[Event]:
        options = options or Options()
        images = any(a.kind == "image" for a in options.attachments)
        if options.task == "image" or (not images and _wants_picture(question, history)):
            yield from self._draw(question, history, mode)
            return
        if not images and (options.task == "review" or wants_review(question, True)):
            files = code_files(question, options.attachments, self.fetch_text)
            repo = None if files else repo_url(question)
            if files or repo:
                yield from self._analyse(files, repo, review)
                if "error" in review:
                    yield "error", review["error"]
                    return
        top = chunks[0].score if chunks else None
        route: Route = "review" if review else classify(question, top, images=images)
        if options.strict and not review:
            route = "sources"
        min_score = self.min_score if options.min_score is None else options.min_score
        shown = [c for c in chunks if c.score >= min_score]
        available = set(self.providers)
        if options.services:
            available &= set(options.services)
            if not available:
                yield (
                    "error",
                    {"status": 422, "detail": "None of the chosen AI services is available here."},
                )
                return
        order = provider_order(mode, route, self.best_order, available)
        if route == "current":
            # Recent events need a web search: services that can search right now first.
            order.sort(
                key=lambda n: not any(map(self.providers[n].searches, self.providers[n].models))
            )
        yield "route", {"route": route, "mode": mode, "providers": order}
        if not order:
            yield "error", {"status": 503, "detail": "No AI service is configured; add an API key."}
            return

        notes = ""
        if options.research is not None and not review:
            research: dict = {}
            yield from self._research(question, options.research, research)
            # What the agent read and found first, then the first search's excerpts.
            merged = {c.symbol_id: c for c in [*research["chunks"], *shown]}
            shown = list(merged.values())[:RESEARCH_EXCERPTS]
            notes = notes_block(research["notes"])

        found: list[WebResult] = []
        if (
            options.strict
            and not shown
            and not any(a.kind == "text" and a.text for a in options.attachments)
        ):
            # Nothing retrieved: the rules' answer, without asking a model to invent one.
            yield "delta", {"text": NOT_IN_SOURCES}
            response = AskResponse(
                question=question,
                answer=NOT_IN_SOURCES,
                citations=[],
                chunks=[],
                model="none",
                complete=True,
                provider="Atlas",
                route=route,
                suggestions=[],
            )
            yield "done", response.model_dump()
            return

        uses_web = options.web_search and not options.strict
        if self.web is not None and uses_web and route not in ("chat", "review"):
            yield "searching", {}
            previous = next((t.content for t in reversed(history) if t.role == "user"), None)
            started = time.monotonic()
            found = self.web.search(search_query(question, previous), recent=route == "current")
            logger.info("web search: %d results in %.1fs", len(found), time.monotonic() - started)
            yield "web", {"sources": [{"title": r.title, "url": r.url} for r in found[:12]]}
        searched = [{"title": r.title, "url": r.url} for r in found]

        system = (
            strict_prompt(options.instructions)
            if options.strict
            else system_prompt(style=options.style, instructions=options.instructions)
        )
        if review:
            system = f"{system}\n\n{REVIEW}"
        if FORMATS.get(options.format):
            system = f"{system}\n\n{FORMATS[options.format]}"
        tuning: dict = {} if options.temperature is None else {"temperature": options.temperature}
        if options.max_tokens:
            tuning["max_tokens"] = options.max_tokens
        today = datetime.now(UTC).date()
        findings = review.get("text", "") or notes
        # Code questions over code excerpts: the user's code-aware prompt.
        code = (
            not options.strict
            and not review
            and wants_code_answer(question, route, [c.language for c in shown])
        )
        turns = conversation(
            question,
            shown,
            history,
            options.attachments,
            web=web_block(found, today) if found else "",
            analysis=findings,
            strict=options.strict and not review,
            code=code,
        )
        panel = self._candidates(order, route, images)
        size = options.council_size or self.council_size
        if size > 1 and len(panel) > 1:
            # The merger needs the web results' links, not their text: a smaller request
            # is quicker and fits free per-minute limits.
            merge_base = conversation(
                question,
                shown,
                history,
                options.attachments,
                web=web_block(found, today, brief=True) if found else "",
                analysis=findings,
                strict=options.strict and not review,
                code=code,
            )
            yield from self._council(
                question,
                route,
                panel,
                order,
                shown,
                system,
                turns,
                tuning,
                searched,
                merge_base,
                # A review's drafts carry code blocks with fixes: keep more of each.
                draft_limit=6000 if review else 3500,
                size=size,
                merger=options.merger,
                keep_drafts=options.include_drafts,
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
            answer = tidy_citations(answer, shown)
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
        draft_limit: int = 3500,
        size: int | None = None,
        merger: str | None = None,
        keep_drafts: bool = False,
    ) -> Iterator[Event]:
        """Seats up to `size` agents, collects their drafts, then merges them; `merger`
        names the service to merge first, if it answered."""
        size = size or self.council_size
        results: queue.Queue = queue.Queue()
        seats = candidates[:size]
        reserve = candidates[size:]

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
                    keep_drafts,
                ).model_dump(),
            )
            return

        yield "merging", {"drafts": len(drafts)}
        merge_turns = with_drafts(
            merge_base or turns, [d.answer for d in drafts[: self.merge_drafts]], draft_limit
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
        if merger:
            chosen = [p for p in merge_order if p[0] == merger and p in answered]
            merge_order = chosen + [p for p in merge_order if p not in chosen]
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
                    keep_drafts,
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
                keep_drafts,
            ).model_dump(),
        )

    def _analyse(self, files: dict[str, str], repo: str | None, review: dict) -> Iterator[Event]:
        """Runs the code analyser on `files`, or on the GitHub repository `repo`, sending
        its progress; leaves `schema` and `text` (or `error`) in `review`."""
        if not repo:
            yield "analysing", {"message": f"Running the code analyser on {len(files)} file(s)"}
            analysis = analyse_files(files)
            review["schema"], review["text"] = to_schema(analysis), files_summary(analysis)
            yield "analysis", review["schema"].model_dump()
            return
        if not _REPO_ANALYSIS.acquire(blocking=False):
            review["error"] = {
                "status": 409,
                "detail": "Another repository is being analysed; try again in a minute.",
            }
            return
        progress: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                report = self.analyse_repo(
                    repo, lambda message: progress.put(("progress", message))
                )
                progress.put(("report", report))
            except RepoTooLarge as error:
                progress.put(("error", {"status": 413, "detail": str(error)}))
            except Exception as error:  # noqa: BLE001 - any failure ends the review politely
                logger.warning("analysis of %s failed: %s", repo, error)
                progress.put(
                    (
                        "error",
                        {
                            "status": 422,
                            "detail": f"{repo} could not be analysed; is it a public GitHub "
                            f"repository? ({type(error).__name__})",
                        },
                    )
                )
            finally:
                _REPO_ANALYSIS.release()

        threading.Thread(target=work, daemon=True).start()
        yield "analysing", {"message": f"Analysing {repo}"}
        while True:
            try:
                kind, value = progress.get(timeout=REPO_ANALYSIS_SECONDS)
            except queue.Empty:
                review["error"] = {
                    "status": 504,
                    "detail": "The repository took too long to analyse.",
                }
                return
            if kind == "progress":
                yield "analysing", {"message": value}
            elif kind == "error":
                review["error"] = value
                return
            else:
                review["schema"] = to_schema(value.analysis, value)
                review["text"] = summary_for_agents(value)
                yield "analysis", review["schema"].model_dump()
                return

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
        keep_drafts: bool = False,
    ) -> AskResponse:
        answer = tidy_citations(answer, shown)
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
            drafts=[
                AgentDraft(
                    agent=f"{d.provider} · {d.model}", seconds=round(d.seconds, 1), answer=d.answer
                )
                for d in drafts
            ]
            if keep_drafts
            else [],
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


def _read_text(http: httpx2.Client, url: str, limit: int = 400_000) -> str:
    response = http.get(url, timeout=20.0, follow_redirects=True)
    response.raise_for_status()
    return response.text[:limit]


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
    if settings.together_api_key:
        images.append(
            TogetherImages(http, settings.together_api_key, settings.together_image_model)
        )
    if settings.gemini_images and settings.gemini_api_key:
        images.append(GeminiImages(http, settings.gemini_api_key, settings.gemini_image_model))
    if settings.horde_enabled:
        images += [
            HordeImages(http, settings.horde_api_key, [model], label=f"AI Horde · {model}")
            for model in _models("horde_image_models")
        ]
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
        planner=settings.assistant_query_planner,
        reranker=settings.assistant_reranker,
        answer_cache=settings.assistant_answer_cache,
        judge_services=[
            n.strip() for n in settings.assistant_judge_services.split(",") if n.strip()
        ],
        fetch_text=lambda url: _read_text(http, url),
        merge_drafts=settings.assistant_merge_drafts,
    )


def _log_answer(question: str, options: Options | None, data: dict) -> None:
    """One line per answer for observability: the query, its rewrites, what was retrieved
    and how relevant, the citation check, the confidence and the seconds per stage."""
    chunks = data.get("chunks", [])
    citations = data.get("citations", [])
    record = {
        "query": question[:300],
        "rewritten": list((options.search_queries if options else ()) or ())[1:],
        "retrieved": [c.get("symbol_id") for c in chunks],
        "scores": [round(c.get("score", 0), 3) for c in chunks],
        "relevance": [c.get("relevance") for c in chunks],
        "route": data.get("route"),
        "model": data.get("model"),
        "answer_chars": len(data.get("answer", "")),
        "citations": len(citations),
        "verified": sum(1 for c in citations if c.get("verified")),
        "confidence": (data.get("confidence") or {}).get("level"),
        "timings": data.get("timings"),
    }
    logger.info("answer %s", json.dumps(record, default=str))


def get_assistant() -> Assistant:
    assistant = _build()
    if not assistant.providers:
        raise HTTPException(503, "No AI service is configured; set GEMINI_API_KEY or another key.")
    return assistant
