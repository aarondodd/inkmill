from inkmill.config import Settings
from inkmill.documents import Document
from inkmill.export.html import available_styles, render_html, export_html, style_css
from inkmill.export.markdown import render
from inkmill.formats import MARKDOWN, TEXT

SAMPLE = """---
title: The Title
author: A. Writer
---
# Heading One

A footnote here.[^1] And ~~gone~~.

| A | B |
|---|--:|
| 1 | 2 |

- [ ] open
- [x] done

Term
: Meaning

> [!WARNING]
> Careful.

```python
x = 1
```

[^1]: The note.
"""


def test_render_extensions():
    out = render(SAMPLE)
    body = out.body
    assert out.title == "The Title"
    assert out.meta["author"] == "A. Writer"
    assert 'class="footnote-ref"' in body and 'class="footnotes"' in body
    assert "<table>" in body and 'style="text-align:right"' in body
    assert 'class="task-list-item-checkbox"' in body and "checked" in body
    assert "<dl>" in body and "<dt>Term</dt>" in body
    assert "markdown-alert-warning" in body
    assert "<s>gone</s>" in body
    assert 'id="heading-one"' in body
    assert 'class="highlight"' in body


def test_title_falls_back_to_first_h1():
    assert render("# Only Heading\n\ntext").title == "Only Heading"
    assert render("no heading").title is None


def test_typographer_toggle():
    assert "“" in render('"quoted"').body
    assert "“" not in render('"quoted"', typographer=False).body


def test_standalone_html_document():
    html = render_html(SAMPLE, style="modern")
    assert html.startswith("<!DOCTYPE html>")
    assert "<title>The Title</title>" in html
    assert '<meta name="author" content="A. Writer">' in html
    assert "--im-measure" in html  # base sheet included
    assert "style: modern" in html


def test_bundled_styles_and_user_override(isolated_dirs):
    cfg, _ = isolated_dirs
    styles = available_styles()
    assert {"classic", "modern", "manuscript", "wordperfect"} <= set(styles)
    assert "_base" not in styles
    (cfg / "styles").mkdir(parents=True)
    (cfg / "styles" / "mine.css").write_text("body { color: red; }")
    (cfg / "styles" / "classic.css").write_text("/* overridden */")
    styles = available_styles()
    assert "mine" in styles
    assert styles["classic"] == "/* overridden */"
    assert "color: red" in style_css("mine")


def test_unknown_style_falls_back_to_classic():
    assert "style: nope" in style_css("nope")


def test_export_plain_text_is_preformatted():
    doc = Document(format=TEXT, text="<b>raw</b>")
    html = export_html(doc, Settings())
    assert "<pre>&lt;b&gt;raw&lt;/b&gt;</pre>" in html


def test_export_uses_settings_style():
    doc = Document(format=MARKDOWN, text="# Hi")
    settings = Settings(export_style="manuscript")
    assert "style: manuscript" in export_html(doc, settings)
