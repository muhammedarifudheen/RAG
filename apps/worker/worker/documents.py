"""Turns a text document into the same shape as an extracted source file.

A document becomes one file whose content is the text re-flowed to short lines,
plus one `section` symbol per passage. Line ranges then work for documents the
way they do for code: a citation points at lines, and the lines can be shown.
"""

from __future__ import annotations

import hashlib
import re
import textwrap
from dataclasses import dataclass

from worker.extract.types import MODULE, FileExtraction, Symbol

SECTION = "section"

LINE_WIDTH = 100
# Passages of roughly this many characters. all-MiniLM-L6-v2 reads at most 256
# word pieces, so longer passages would be embedded only in part.
PASSAGE_CHARS = 1000

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
_UNSAFE_PATH = re.compile(r"[^\w./~-]+", re.UNICODE)


@dataclass
class Document:
    path: str  # unique within the knowledge base; see `document_path`
    title: str
    text: str  # plain text or Markdown; `#` lines are headings
    url: str | None = None


def document_path(*parts: str) -> str:
    """A path safe to appear inside a `[path:start-end]` citation: no colons,
    brackets or spaces, since those delimit the citation."""
    cleaned = []
    for part in parts:
        segments = [_UNSAFE_PATH.sub("_", s).strip("_.") for s in part.split("/")]
        cleaned.extend(s for s in segments if s)
    return "/".join(cleaned)[:240] or "untitled"


@dataclass
class _Block:
    lines: list[str]
    heading: tuple[int, str] | None = None  # (level, text) if this block is a heading


def _blocks(text: str) -> list[_Block]:
    """Splits text into headings and paragraphs, wrapping paragraphs to LINE_WIDTH."""
    blocks: list[_Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            wrapped = textwrap.wrap(" ".join(paragraph), LINE_WIDTH, break_long_words=False)
            # Passages are cut between blocks, so a paragraph longer than a passage
            # is divided here; otherwise it would be embedded only in part.
            piece: list[str] = []
            for line in wrapped or [""]:
                if piece and sum(map(len, piece)) + len(line) > PASSAGE_CHARS:
                    blocks.append(_Block(piece))
                    piece = []
                piece.append(line)
            blocks.append(_Block(piece))
            paragraph.clear()

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        heading = _HEADING.match(line)
        if not line:
            flush()
        elif heading:
            flush()
            title = heading[2].strip()
            if title:
                blocks.append(_Block([f"{heading[1]} {title}"], (len(heading[1]), title)))
        elif _LIST_ITEM.match(line) or line.startswith("|"):
            # List items and table rows keep their own lines.
            flush()
            indent = "  " if _LIST_ITEM.match(line) else ""
            wrapped = textwrap.wrap(
                line, LINE_WIDTH, subsequent_indent=indent, break_long_words=False
            )
            previous = blocks[-1] if blocks else None
            if (
                previous is not None
                and previous.heading is None
                and (_LIST_ITEM.match(previous.lines[0]) or previous.lines[0].startswith("|"))
                and sum(map(len, previous.lines)) < PASSAGE_CHARS
            ):
                # Consecutive items form one list, until it is as long as a passage.
                previous.lines.extend(wrapped)
            else:
                blocks.append(_Block(wrapped))
        else:
            paragraph.append(line)
    flush()
    return blocks


def build_extraction(document: Document) -> FileExtraction:
    """Re-flows the document and cuts it into passages under their headings."""
    blocks = _blocks(document.text)
    if not any(b.heading is None for b in blocks):
        raise ValueError(f"No readable text found in {document.title!r}.")

    lines: list[str] = []
    passages: list[tuple[str, int, int, str]] = []  # (heading path, start, end, text)
    trail: list[tuple[int, str]] = []
    current: list[str] = []
    start = 0
    size = 0

    def heading_path() -> str:
        return " › ".join(title for _, title in trail)

    def close() -> None:
        nonlocal current, size
        body = [line for line in current if line and not line.startswith("#")]
        if body:
            passages.append((heading_path(), start, len(lines), "\n".join(current).strip()))
        current, size = [], 0

    for block in blocks:
        if block.heading:
            close()
            level, title = block.heading
            trail = [(lv, t) for lv, t in trail if lv < level] + [(level, title)]
        elif size and size + sum(len(line) for line in block.lines) > PASSAGE_CHARS:
            # Close before the passage would outgrow what the embedding model reads.
            close()
        if lines:
            lines.append("")
        if not current:
            start = len(lines) + 1
        else:
            current.append("")
        lines.extend(block.lines)
        current.extend(block.lines)
        if not block.heading:
            size += sum(len(line) for line in block.lines)
    close()

    content = "\n".join(lines) + "\n"
    module = Symbol(
        name=document.path,
        kind=MODULE,
        path=document.path,
        start_line=1,
        end_line=len(lines),
        signature=document.title[:200],
        text=f"{document.title}\n{content[:2000]}",
    )
    extraction = FileExtraction(
        path=document.path,
        language="text",
        hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        loc=len(lines),
        content=content,
        symbols=[module],
    )

    seen: dict[str, int] = {}
    for heading, first, last, text in passages:
        label = heading or document.title
        seen[label] = seen.get(label, 0) + 1
        name = label if seen[label] == 1 else f"{label} ({seen[label]})"
        extraction.symbols.append(
            Symbol(
                name=name[:300],
                kind=SECTION,
                path=document.path,
                start_line=first,
                end_line=last,
                signature=(heading or None) and heading[:200],
                # The title and headings give a short passage its context when embedded.
                text=f"{document.title} — {heading}\n{text}" if heading else f"{document.title}\n{text}",
                parent=module,
            )
        )
    return extraction
