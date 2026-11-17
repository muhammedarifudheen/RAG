"""The answer contract: every answer ends in one of five states, and none is a bare refusal.

    VERIFIED     answered from the knowledge base or a primary source, with citations.
    REPORTED     answered from the web, attributed with its URLs and an as_of date.
    INFERRED     derived from evidence, with the reasoning shown and labelled an inference.
    UNVERIFIED   the model's own knowledge, no source: labelled, never presented as fact.
    EVIDENCE_GAP nothing found anywhere: the tools tried, the closest passage, the next step.

Strict sources only never yields UNVERIFIED or REPORTED: with nothing in the sources it is an
EVIDENCE_GAP. Chat and pictures make no factual claim, so they carry no state.

The sentence "I don't have that in the knowledge base" is banned from every output: the
streamed text is held back far enough to catch it before it leaves, a final answer holding it
is regenerated, and after that replaced by the evidence-gap report.

This is derived on top of the older `epistemic` field (known, inferred, partial, absent,
conflicted, general, web), which is unchanged; nothing here reads or writes the database.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime

VERIFIED = "VERIFIED"
REPORTED = "REPORTED"
INFERRED = "INFERRED"
UNVERIFIED = "UNVERIFIED"
EVIDENCE_GAP = "EVIDENCE_GAP"
STATES = (VERIFIED, REPORTED, INFERRED, UNVERIFIED, EVIDENCE_GAP)

# Compared after normalising case, apostrophes and spacing, so the curly and the straight
# apostrophe, and a line break inside the sentence, are all caught.
BANNED_PHRASES = ("I don't have that in the knowledge base",)

# How many times an answer holding a banned phrase is asked for again before the evidence-gap
# report replaces it.
MAX_REGENERATIONS = 2
REGENERATE_INSTRUCTION = (
    'Never write the sentence "I don\'t have that in the knowledge base", or a refusal like '
    "it. If the sources do not answer, say what was searched, what came closest and what to "
    "do next, or answer from your own knowledge and say plainly that it is unverified."
)

UNVERIFIED_NOTE = (
    "**Unverified:** this comes from the model's own knowledge, with no source to check it "
    "against. Treat it as a lead, not a fact."
)
INFERRED_NOTE = (
    "**Inference:** no source states this directly; it is derived from the evidence below, "
    "with the reasoning shown."
)
_INFERRED_OPENERS = ("based on", "inference", "inferred", "this implies", "from this")

FLOOR_NOTE = "below the relevance floor"


def normalize(text: str) -> str:
    """Lower case, one kind of apostrophe, spacing collapsed."""
    return " ".join(text.replace("’", "'").replace("‘", "'").lower().split())


_BANNED = tuple(normalize(p) for p in BANNED_PHRASES)


def find_banned(text: str | None) -> str | None:
    """The banned phrase in `text`, if any."""
    if not text:
        return None
    flat = normalize(text)
    return next((p for p in BANNED_PHRASES if normalize(p) in flat), None)


def has_banned(*texts: str | None) -> bool:
    return any(find_banned(t) for t in texts)


def scrub(text: str) -> str:
    """`text` with any banned phrase replaced, for places a regeneration cannot reach (a
    council agent's own draft)."""
    for phrase in BANNED_PHRASES:
        words = [re.escape(w).replace("'", "['’]") for w in phrase.split()]
        text = re.sub(r"\s+".join(words), "no source found", text, flags=re.IGNORECASE)
    return text


class BannedGuard:
    """Holds streamed text back just far enough that a banned phrase is seen before any of it
    is sent. `feed` returns the text that is safe to send now; `hit` turns true once the phrase
    has appeared, after which nothing more is released (the caller replaces the answer)."""

    def __init__(self) -> None:
        self.hold = max(len(p) for p in BANNED_PHRASES) + 8
        self.pending = ""
        self.hit = False

    def feed(self, text: str) -> str:
        if self.hit:
            return ""
        self.pending += text
        if has_banned(self.pending):
            self.hit = True
            self.pending = ""
            return ""
        keep = max(0, len(self.pending) - self.hold)
        out, self.pending = self.pending[:keep], self.pending[keep:]
        return out

    def flush(self) -> str:
        out = "" if self.hit else self.pending
        self.pending = ""
        return out


# --- The state of an answer ----------------------------------------------------------------


def derive_state(data: Mapping, *, strict: bool = False) -> str | None:
    """The answer's state from what it carries: the older epistemic state, its citations, its
    web sources. None for a route that makes no claim (chat, pictures)."""
    if data.get("answer_state") in STATES:
        state = data["answer_state"]
    else:
        route = data.get("route")
        epistemic = data.get("epistemic")
        verified = sum(1 for c in data.get("citations") or [] if c.get("verified"))
        if route in ("chat", "image", "vision") and not epistemic:
            return None
        if route == "review":
            state = VERIFIED if data.get("analysis") else INFERRED
        elif epistemic == "absent":
            state = EVIDENCE_GAP
        elif epistemic == "known":
            state = VERIFIED if verified else INFERRED
        elif epistemic in ("inferred", "partial", "conflicted"):
            state = INFERRED
        elif epistemic == "web" or (not epistemic and data.get("web_sources")):
            state = REPORTED
        elif epistemic == "general":
            state = UNVERIFIED
        elif data.get("chunks") and verified:
            state = VERIFIED
        else:
            state = UNVERIFIED
    # Strict keeps its promise: nothing but the sources.
    if strict and state in (UNVERIFIED, REPORTED):
        return EVIDENCE_GAP
    return state


# --- The evidence-gap report ---------------------------------------------------------------


def tools_tried(
    *,
    queries: Sequence[str] = (),
    judged: int | None = None,
    kept: int | None = None,
    candidates: int | None = None,
    strict: bool = False,
    grounded: bool = False,
    web_enabled: bool = True,
    web_results: int | None = None,
    floor: float = 0.3,
) -> list[str]:
    """What was searched, for the report: one line per tool, with what it returned."""
    lines = []
    searches = max(len(queries), 1)
    lines.append(
        f"Knowledge base: vector and keyword search, {searches} "
        f"{'query' if searches == 1 else 'queries'}; passages need a similarity of at least "
        f"{floor:.2f} to be used."
    )
    if candidates is not None:
        lines.append(
            f"Relevance judge: {judged or 0} of {candidates} candidate passages scored, "
            f"{kept or 0} kept."
        )
    if strict:
        lines.append("Web search: not used (Strict sources only is on).")
    elif grounded:
        lines.append("Web search: not used (this server answers from its knowledge base only).")
    elif not web_enabled:
        lines.append("Web search: switched off in Settings.")
    else:
        lines.append(
            f"Web search: {'no results' if not web_results else f'{web_results} results'}."
        )
    return lines


def closest_match(chunk: Mapping | None) -> dict | None:
    """The nearest passage found, even though it was not good enough, for the report."""
    if not chunk:
        return None
    snippet = (chunk.get("snippet") or "").strip()
    lines = snippet.splitlines()[:4]
    return {
        "file": chunk.get("file"),
        "start_line": chunk.get("start_line"),
        "end_line": chunk.get("end_line"),
        "score": round(float(chunk.get("score") or 0.0), 3),
        "citation": chunk.get("citation"),
        "snippet": "\n".join(lines)[:400],
    }


def next_steps(*, closest: dict | None, strict: bool, grounded: bool) -> list[str]:
    steps = []
    if closest:
        steps.append(
            "Open the closest passage above: it may be the right place under different wording."
        )
    steps.append(
        "Rephrase with the exact name you expect to find (a function, file, setting or term): "
        "keyword search matches names."
    )
    steps.append(
        "Add a source that covers this: paste a link, or upload a file, on the Ingest page."
    )
    if strict and not grounded:
        steps.append("Turn off Strict sources only to let Atlas search the web as well.")
    return steps


def evidence_gap(
    *, tools: Sequence[str], closest: dict | None, steps: Sequence[str], floor: float
) -> tuple[str, dict]:
    """The report and its structured form. Never a one-line "I don't know"."""
    out = ["**Evidence gap.** Nothing I could find answers this, and I will not guess.", ""]
    out.append("**Tools tried**")
    out += [f"- {line}" for line in tools]
    out += ["", "**Closest match**"]
    if closest:
        where = closest.get("citation") or f"{closest['file']}:{closest['start_line']}"
        note = f", {FLOOR_NOTE} ({floor:.2f})" if closest["score"] < floor else ""
        out.append(f"{where} (similarity {closest['score']:.2f}{note})")
        out += [f"> {line}" for line in (closest.get("snippet") or "").splitlines() if line.strip()]
    else:
        out.append("Nothing in the knowledge base came close.")
    out += ["", "**Next step**"]
    out += [f"{i}. {step}" for i, step in enumerate(steps, 1)]
    text = "\n".join(out)
    return text, {"tools_tried": list(tools), "closest": closest, "next_steps": list(steps)}


# --- Making the answer say which state it is in -------------------------------------------


def as_of_date(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).date().isoformat()


def reported_block(web_sources: Iterable[Mapping], as_of: str) -> str:
    links = [s for s in web_sources if s.get("url")]
    if not links:
        return ""
    lines = [f"**Reported from the web** (as of {as_of}):"]
    lines += [f"- {s.get('title') or s['url']}: {s['url']}" for s in links[:12]]
    return "\n".join(lines)


def label(data: dict, state: str | None, *, now: datetime | None = None) -> dict:
    """The answer with the note its state calls for: unverified is said, an inference is
    labelled, a web answer lists its URLs and date. Verified answers carry their citations."""
    answer = data.get("answer") or ""
    if state == UNVERIFIED and answer.strip() and UNVERIFIED_NOTE not in answer:
        return {**data, "answer": f"{UNVERIFIED_NOTE}\n\n{answer}"}
    if (
        state == INFERRED
        and answer.strip()
        and not answer.lstrip().lower().startswith(_INFERRED_OPENERS)
        and INFERRED_NOTE not in answer
        and not (data.get("uncertainty") or {}).get("exceeded")  # a withheld answer opens as such
    ):
        return {**data, "answer": f"{INFERRED_NOTE}\n\n{answer}"}
    if state == REPORTED and answer.strip():
        as_of = as_of_date(now)
        block = reported_block(data.get("web_sources") or [], as_of)
        return {
            **data,
            "as_of": as_of,
            "answer": f"{answer}\n\n{block}" if block and block not in answer else answer,
        }
    return data


def apply(
    data: dict,
    *,
    strict: bool,
    grounded: bool,
    web_enabled: bool,
    queries: Sequence[str],
    reranking: Mapping | None,
    closest: Mapping | None,
    floor: float,
    now: datetime | None = None,
) -> dict:
    """The response with its `answer_state`, and the answer reworded to say it: an evidence-gap
    report replaces a missing or refused answer. Idempotent."""
    state = derive_state(data, strict=strict)
    if state is None:
        return data
    data = {**data, "answer_state": state}
    if state == EVIDENCE_GAP:
        if data.get("evidence_gap"):  # built where nothing was found
            return data
        found = closest or (data.get("chunks") or [None])[0]
        near = closest_match(found)
        tools = tools_tried(
            queries=queries,
            candidates=(reranking or {}).get("candidates"),
            judged=(reranking or {}).get("judged"),
            kept=(reranking or {}).get("kept"),
            strict=strict,
            grounded=grounded,
            web_enabled=web_enabled,
            web_results=len(data.get("web_sources") or []),
            floor=floor,
        )
        text, gap = evidence_gap(
            tools=tools,
            closest=near,
            steps=next_steps(closest=near, strict=strict, grounded=grounded),
            floor=floor,
        )
        return {**data, "answer": text, "evidence_gap": gap, "citations": []}
    return label(data, state, now=now)


def clean_drafts(data: dict) -> dict:
    """A council agent's draft may hold the banned sentence: it is rewritten, since a draft is
    shown as it was written and cannot be asked for again."""
    drafts = data.get("drafts") or []
    if not any(has_banned(d.get("answer")) for d in drafts):
        return data
    return {**data, "drafts": [{**d, "answer": scrub(d.get("answer", ""))} for d in drafts]}
