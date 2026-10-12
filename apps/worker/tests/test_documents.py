import hashlib
import itertools

import pytest

from worker.documents import PASSAGE_CHARS, Document, build_extraction, document_path
from worker.embed import symbol_text

ARTICLE = """# Alan Turing

Alan Turing was an English mathematician and computer scientist.

## Early life

Turing was born in Maida Vale, London.

He studied at King's College, Cambridge.

## Work

### Codebreaking

- Worked at Bletchley Park
- Designed the Bombe
"""


def sections(extraction):
    return [(s.name, s.start_line, s.end_line) for s in extraction.symbols[1:]]


def test_document_becomes_a_file_with_one_section_per_heading():
    f = build_extraction(Document("wikipedia/en/Alan_Turing", "Alan Turing", ARTICLE))

    assert f.path == "wikipedia/en/Alan_Turing"
    assert f.language == "text"
    assert f.content.split("\n") == [
        "# Alan Turing",  # 1
        "",
        "Alan Turing was an English mathematician and computer scientist.",  # 3
        "",
        "## Early life",  # 5
        "",
        "Turing was born in Maida Vale, London.",  # 7
        "",
        "He studied at King's College, Cambridge.",  # 9
        "",
        "## Work",  # 11
        "",
        "### Codebreaking",  # 13
        "",
        "- Worked at Bletchley Park",  # 15
        "- Designed the Bombe",  # 16
        "",
    ]
    assert f.loc == 16
    assert f.hash == hashlib.sha256(f.content.encode()).hexdigest()

    # Each section starts at its heading line, so the snippet shows the heading.
    # "## Work" has no text of its own, so it is not a section; its child is.
    assert sections(f) == [
        ("Alan Turing", 1, 3),
        ("Alan Turing › Early life", 5, 9),
        ("Alan Turing › Work › Codebreaking", 13, 16),
    ]


def test_the_module_symbol_is_the_whole_document(tmp_path):
    f = build_extraction(Document("uploads/turing.txt", "Alan Turing", ARTICLE))
    module = f.module
    assert (module.name, module.kind, module.start_line, module.end_line) == (
        "uploads/turing.txt",
        "module",
        1,
        16,
    )
    assert module.signature == "Alan Turing"
    assert all(s.kind == "section" and s.path == f.path for s in f.symbols[1:])


def test_section_text_carries_title_and_heading_for_embedding():
    f = build_extraction(Document("x", "Alan Turing", ARTICLE))
    early = f.symbols[2]

    assert early.signature == "Alan Turing › Early life"
    assert early.text.startswith("Alan Turing — Alan Turing › Early life\n## Early life")
    assert "Maida Vale" in early.text and "Cambridge" in early.text
    assert symbol_text(early).startswith("section Alan Turing › Early life in x\n")


def test_long_text_is_split_into_passages_and_long_lines_are_wrapped():
    paragraph = "The quick brown fox jumps over the lazy dog. " * 6  # about 270 characters
    f = build_extraction(Document("x", "Fox", "\n\n".join([paragraph] * 12)))

    assert all(len(line) <= 100 for line in f.content.split("\n"))
    names = [s.name for s in f.symbols[1:]]
    # Three paragraphs fit in a passage; a fourth would exceed it. Numbered when a
    # heading has several.
    assert names == ["Fox", "Fox (2)", "Fox (3)", "Fox (4)"]
    for section in f.symbols[1:]:
        assert len(section.text) < PASSAGE_CHARS + 100
    # Passages do not overlap and together cover the text.
    ranges = [(s.start_line, s.end_line) for s in f.symbols[1:]]
    assert all(a[1] < b[0] for a, b in itertools.pairwise(ranges))
    assert ranges[0][0] == 1 and ranges[-1][1] == f.loc


def test_a_single_huge_paragraph_or_list_is_still_divided():
    # No blank lines anywhere: one paragraph of about 6,000 characters.
    wall = "Every sentence in this paragraph follows the last without a break. " * 90
    f = build_extraction(Document("x", "Wall", wall))
    assert len(f.symbols) - 1 >= 5
    assert all(len(s.text) < PASSAGE_CHARS + 300 for s in f.symbols[1:])

    items = "\n".join(f"- item number {i} has a little text of its own to carry" for i in range(120))
    g = build_extraction(Document("y", "List", items))
    assert len(g.symbols) - 1 >= 4
    assert all(len(s.text) < PASSAGE_CHARS * 2 + 300 for s in g.symbols[1:])
    # Nothing is lost: every item is still in the stored text, on its own line.
    assert g.content.count("- item number") == 120


def test_plain_text_without_headings_uses_the_title():
    f = build_extraction(Document("uploads/note.txt", "note", "Just one line.\r\nAnd another."))
    assert f.content == "Just one line. And another.\n"
    assert sections(f) == [("note", 1, 1)]


def test_documents_without_text_are_rejected():
    for text in ("", "   \n\n  ", "# Only a heading\n\n## And another"):
        with pytest.raises(ValueError, match="No readable text"):
            build_extraction(Document("x", "Empty", text))


def test_document_paths_are_safe_inside_a_citation():
    assert document_path("wikipedia", "en", "Alan Turing") == "wikipedia/en/Alan_Turing"
    assert document_path("web", "example.com", "a/b?q=1&x=[2]") == "web/example.com/a/b_q_1_x_2"
    assert document_path("uploads", "My Book: Vol. 1.pdf") == "uploads/My_Book_Vol._1.pdf"
    assert document_path("wikipedia", "de", "Köln") == "wikipedia/de/Köln"
    for path in (document_path("web", "h", "x:y z[1]"), document_path("uploads", "../../etc/passwd")):
        assert not set(path) & set(":[] \n")
        assert ".." not in path.split("/")
    assert document_path("", "///") == "untitled"
