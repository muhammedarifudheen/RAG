"""Chooses which model services answer a question, and in what order.

Two modes:
- "auto" routes by question type: the knowledge base, code, recent events,
  reasoning, small talk or anything else. Each type has the order of services
  that suit it, and within a service its coding or reasoning models come first
  when the question calls for them.
- "best" ignores the type and starts with the strongest service configured.
Two types are set by what comes with the question rather than its wording: a
picture to draw ("image", whose prompt a fast model writes) and attached images
("vision", for the services that can see them); "best" keeps those orders too.
Either way, a service that is not configured is skipped, and one that fails
hands over to the next.
"""

from __future__ import annotations

import re
from typing import Literal

Mode = Literal["auto", "best"]
Route = Literal["sources", "code", "current", "reasoning", "chat", "general", "image", "vision"]

# Strongest-suited first. Gemini leads where a web search helps, since only it
# can search; Groq leads small talk because it answers fastest.
ROUTE_ORDER: dict[str, tuple[str, ...]] = {
    "sources": ("gemini", "claude", "openrouter", "mistral", "groq"),
    "code": ("claude", "openrouter", "gemini", "mistral", "groq"),
    "current": ("gemini", "claude", "openrouter", "mistral", "groq"),
    "reasoning": ("claude", "openrouter", "gemini", "groq", "mistral"),
    "chat": ("groq", "gemini", "mistral", "openrouter", "claude"),
    "general": ("gemini", "claude", "openrouter", "mistral", "groq"),
    # Writing a picture's prompt is quick work: the fastest first.
    "image": ("groq", "gemini", "mistral", "openrouter", "claude"),
    # Services whose models see images reliably first.
    "vision": ("gemini", "claude", "mistral", "openrouter", "groq"),
}

# Routes that keep their own order in "best" mode too.
FIXED_ROUTES = ("image", "vision")

# A knowledge-base excerpt at least this similar means the question is about the sources.
SOURCES_SCORE = 0.45

_CODE = re.compile(
    r"```|\b(code|function|class|method|bug|error|exception|traceback|stack trace|compile|"
    r"python|javascript|typescript|java|golang|rust|c\+\+|c#|sql|regex|api|json|html|css|"
    r"react|docker|git|npm|pip|script|refactor|debug|algorithm|implement)\b|\w+\(\)",
    re.IGNORECASE,
)
_CURRENT = re.compile(
    r"\b(today|tonight|yesterday|tomorrow|now|currently|current|latest|recent|recently|news|"
    r"this (week|month|year)|right now|price|prices|stock|weather|score|who won|election|"
    r"release date|20[2-9]\d)\b",
    re.IGNORECASE,
)
_REASONING = re.compile(
    r"\b(prove|proof|calculate|compute|solve|equation|integral|derivative|probability|"
    r"step by step|logic|puzzle|riddle|how many|optimi[sz]e|estimate)\b|[0-9]\s*[-+*/^]\s*[0-9]",
    re.IGNORECASE,
)
_IMAGE = re.compile(
    r"^\s*(please\s+|can you\s+|could you\s+)?("
    r"(draw|paint|sketch|illustrate)\b|"
    r"(generate|create|make|design|render|produce)\s+(me\s+)?(an?\s+|some\s+|the\s+)?"
    r"(\w+\s+){0,3}(image|picture|photo|drawing|illustration|painting|logo|icon|artwork|"
    r"wallpaper|portrait|poster)s?\b|"
    r"(an?\s+)?(image|picture|photo|drawing|illustration|painting)\s+of\b)",
    re.IGNORECASE,
)
# "image" in the software sense: a Docker image, a disk image.
_SOFTWARE_IMAGE = re.compile(
    r"\b(docker|container|disk|iso|vm|machine|system|base|boot|os|kernel)\s+images?\b",
    re.IGNORECASE,
)
_CHAT = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening)|how are you|"
    r"who are you|what can you do)\b",
    re.IGNORECASE,
)

# Model names that mark a service's coding or reasoning models.
_CODE_MODELS = ("coder", "codestral", "code")
_REASONING_MODELS = ("r1", "reason", "think", "gpt-oss", "qwq", "magistral")
_SEARCH_MODELS = ("compound",)


def wants_image(question: str) -> bool:
    """True if the question asks for a picture to be drawn."""
    return bool(_IMAGE.match(question)) and not _SOFTWARE_IMAGE.search(question)


def classify(question: str, top_score: float | None, *, images: bool = False) -> Route:
    """The question's type, from its wording and how well the knowledge base matches it.
    With images attached it is "vision", so the services that can see them answer."""
    if images:
        return "vision"
    if _CHAT.match(question) and len(question) < 60:
        return "chat"
    if top_score is not None and top_score >= SOURCES_SCORE:
        return "sources"
    if _CODE.search(question):
        return "code"
    if _CURRENT.search(question):
        return "current"
    if _REASONING.search(question):
        return "reasoning"
    return "general"


def provider_order(mode: Mode, route: Route, best_order: str, available: set[str]) -> list[str]:
    """The configured services to try, first choice first."""
    if mode == "best" and route not in FIXED_ROUTES:
        order = [name.strip() for name in best_order.split(",") if name.strip()]
    else:
        order = list(ROUTE_ORDER[route])
    return [name for name in order if name in available]


def model_order(models: list[str], route: Route) -> list[str]:
    """A service's models with the ones suited to the route first (coding, reasoning, or
    web-searching models), otherwise as configured."""
    marks = {"code": _CODE_MODELS, "reasoning": _REASONING_MODELS, "current": _SEARCH_MODELS}.get(
        route, ()
    )
    if not marks:
        return list(models)
    return sorted(models, key=lambda model: not any(mark in model.lower() for mark in marks))
