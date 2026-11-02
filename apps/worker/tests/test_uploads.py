"""Word documents and code files as uploads."""

import zipfile

import pytest

from worker import pipeline
from worker.config import Settings
from worker.sources import UPLOAD_TYPES, SourceError, load_upload

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def paragraph(text, style=None, listed=False):
    props = ""
    if style or listed:
        inner = (f'<w:pStyle w:val="{style}"/>' if style else "") + (
            "<w:numPr><w:numId w:val='1'/></w:numPr>" if listed else ""
        )
        props = f"<w:pPr>{inner}</w:pPr>"
    return f"<w:p>{props}<w:r><w:t>{text}</w:t></w:r></w:p>"


def docx(path, body):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>"
        )
    return path


def test_a_word_document_keeps_its_headings_lists_and_tables(tmp_path):
    table = (
        "<w:tbl><w:tr><w:tc>"
        + paragraph("Key")
        + "</w:tc><w:tc>"
        + paragraph("Use")
        + "</w:tc></w:tr>"
        "<w:tr><w:tc>"
        + paragraph("salt")
        + "</w:tc><w:tc>"
        + paragraph("a | b")
        + "</w:tc></w:tr></w:tbl>"
    )
    body = (
        paragraph("Signing guide", "Title")
        + paragraph("Keys", "Heading2")
        + paragraph("Rotate them yearly.")
        + paragraph("Never commit one", listed=True)
        + paragraph("   ")
        + table
    )
    loaded = load_upload(docx(tmp_path / "guide.docx", body), "Signing Guide.docx")
    document = loaded.documents[0]
    assert document.path == "uploads/Signing_Guide.docx"
    assert document.text == (
        "# Signing guide\n\n## Keys\n\nRotate them yearly.\n\n- Never commit one\n\n"
        "| Key | Use |\n| --- | --- |\n| salt | a \\| b |"
    )


def test_broken_or_empty_word_documents_are_refused(tmp_path):
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip")
    with pytest.raises(SourceError, match="Word document"):
        load_upload(broken, "broken.docx")
    with pytest.raises(SourceError, match="No readable text"):
        load_upload(docx(tmp_path / "empty.docx", paragraph(" ")), "empty.docx")


def test_docx_and_code_files_can_be_uploaded():
    assert {".docx", ".py", ".ts", ".tsx", ".go"} <= set(UPLOAD_TYPES)


def test_an_uploaded_code_file_is_parsed_like_a_repository(tmp_path, monkeypatch):
    source = tmp_path / "upload.py"
    source.write_text("def sign(value):\n    return value\n")
    seen = {}

    def directory(root, **kwargs):
        seen["files"] = sorted(p.name for p in root.iterdir())
        seen.update(kwargs)
        return pipeline.IngestResult(files=1, symbols=2, edges=0)

    monkeypatch.setattr(pipeline, "ingest_directory", directory)
    monkeypatch.setattr(
        pipeline, "_open_database", lambda settings: type("E", (), {"dispose": lambda self: None})()
    )
    monkeypatch.setattr(pipeline, "_load_embedder", lambda settings, progress: None)
    monkeypatch.setattr(pipeline, "ingest_documents", lambda *a, **k: pytest.fail("not a document"))
    result = pipeline.ingest_upload(
        source, "..\\tools/My signer.py", settings=Settings(database_url="postgresql://x")
    )
    assert result.symbols == 2
    assert seen["files"] == ["My_signer.py"]
    assert seen["prefix"] == "uploads/"
    assert seen["source"].kind == "upload" and seen["source"].key == "upload:..\\tools/my signer.py"
