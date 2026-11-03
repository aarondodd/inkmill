from inkmill import frontmatter as fm

DOC = """---
title: Chapter 2  # working title
# a comment the writer left
parent: ../novel.md
related:
  - a.md
  - "b c.md"
tags: [x, 'y, z']
nested:
  key: value
---
Body text.
"""


def test_read_scalars_and_lists():
    meta = fm.read(DOC)
    assert meta["title"] == "Chapter 2"
    assert meta["parent"] == "../novel.md"
    assert meta["related"] == ["a.md", "b c.md"]
    assert meta["tags"] == ["x", "y, z"]


def test_update_touches_only_named_keys():
    out = fm.update(DOC, {"related": None, "next": "ch3.md"})
    assert "# a comment the writer left" in out
    assert "title: Chapter 2  # working title" in out
    assert "nested:\n  key: value" in out
    assert "related" not in out
    assert "next: ch3.md" in out
    assert out.endswith("---\nBody text.\n")
    assert fm.read(out)["parent"] == "../novel.md"


def test_long_lists_become_block_lists_and_round_trip():
    items = ["one.md", "two.md", "three.md"]
    out = fm.update(DOC, {"parent": items})
    assert "parent:\n  - one.md\n  - two.md\n  - three.md" in out
    assert fm.read(out)["parent"] == items


def test_adds_and_removes_whole_block():
    added = fm.update("Just text.\n", {"parent": "x.md"})
    assert added == "---\nparent: x.md\n---\nJust text.\n"
    assert fm.update(added, {"parent": None}) == "Just text.\n"
    assert fm.update("Just text.\n", {"parent": None}) == "Just text.\n"


def test_values_needing_quotes_survive():
    out = fm.update("", {"title": "Part one: the start", "related": ["a, b.md", "c.md"]})
    meta = fm.read(out)
    assert meta["title"] == "Part one: the start"
    assert meta["related"] == ["a, b.md", "c.md"]


def test_no_front_matter():
    assert fm.read("# Heading\n") == {}
    assert fm.split("---\nunterminated") == (None, "---\nunterminated")
