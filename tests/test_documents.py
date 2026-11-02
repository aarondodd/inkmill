from pathlib import Path

from inkmill.documents import Document, DocumentList, count_words
from inkmill.formats import MARKDOWN, TEXT, builtin_formats


def test_count_words_ignores_markup():
    assert count_words("# Title\n\n- one **two** [three](http://x.y)\n| a | b |") == 6
    assert count_words("") == 0
    assert count_words("don't stop-me now") == 3


def test_document_roundtrip_normalizes_newlines(tmp_path: Path):
    path = tmp_path / "a.md"
    path.write_bytes(b"\xef\xbb\xbfline one\r\nline two\r\n")
    doc = Document.from_file(path, MARKDOWN)
    assert doc.text == "line one\nline two\n"
    assert not doc.dirty
    doc.text += "three"
    assert doc.dirty
    doc.save()
    assert path.read_bytes() == b"line one\nline two\nthree\n"
    assert not doc.dirty


def test_document_list_cycle_and_remove():
    docs = DocumentList()
    a = docs.add(Document(format=MARKDOWN))
    b = docs.add(Document(format=MARKDOWN))
    assert (a.title, b.title) == ("Untitled", "Untitled 2")
    assert docs.active is b
    assert docs.cycle(1) is a
    docs.remove(a)
    assert docs.active is b
    docs.remove(b)
    assert docs.active is None


def test_pristine_untitled_is_replaced(tmp_path: Path):
    docs = DocumentList()
    blank = docs.add(Document(format=MARKDOWN))
    opened = Document(format=MARKDOWN, path=tmp_path / "x.md")
    assert docs.replace_if_pristine(opened) is blank
    assert len(docs) == 0


def test_format_for_path():
    formats = builtin_formats()
    assert formats.for_path(Path("x.MD")) is MARKDOWN
    assert formats.for_path(Path("x.txt")) is TEXT
    assert formats.for_path(Path("x.unknown")) is TEXT
    assert ".markdown" in formats.document_extensions()
