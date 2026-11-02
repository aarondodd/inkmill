"""Standalone HTML export with a selectable CSS style sheet.

Styles ship inside the package (``export/styles/*.css``). Users add or override
styles by dropping a ``.css`` file into ``<config dir>/styles/``; a user file
with the same name as a bundled one wins.

A style sheet may name its Pygments code theme in a header comment::

    /* inkmill: pygments=monokai */
"""

from __future__ import annotations

import html
import re
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import config_dir
from .markdown import render

if TYPE_CHECKING:
    from ..config import Settings
    from ..documents import Document

_PYGMENTS_HINT = re.compile(r"inkmill:\s*pygments\s*=\s*([\w-]+)")

TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="Inkmill">
{meta}<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
<article class="inkmill-document">
{body}
</article>
</body>
</html>
"""


def user_styles_dir() -> Path:
    return config_dir() / "styles"


def _bundled(name: str) -> str:
    return resources.files("inkmill.export").joinpath("styles", name).read_text(encoding="utf-8")


def available_styles() -> dict[str, str]:
    """Map style name to CSS text, bundled first, user styles overriding.

    Names starting with an underscore are partials, not selectable styles.
    """
    styles: dict[str, str] = {}
    pkg = resources.files("inkmill.export").joinpath("styles")
    for entry in sorted(pkg.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".css") and not entry.name.startswith("_"):
            styles[entry.name[:-4]] = entry.read_text(encoding="utf-8")
    user_dir = user_styles_dir()
    if user_dir.is_dir():
        for path in sorted(user_dir.glob("*.css")):
            if path.stem.startswith("_"):
                continue
            try:
                styles[path.stem] = path.read_text(encoding="utf-8")
            except OSError:
                continue
    return styles


def style_css(name: str) -> str:
    styles = available_styles()
    style = styles.get(name) or styles.get("classic", "")
    css = _bundled("_base.css") + "\n/* style: " + name + " */\n" + style
    match = _PYGMENTS_HINT.search(style)
    pyg_style = match.group(1) if match else "default"
    try:
        from pygments.formatters import HtmlFormatter

        css += "\n/* code highlighting */\n" + HtmlFormatter(style=pyg_style).get_style_defs(".highlight")
    except Exception:
        pass
    return css


def render_html(text: str, *, style: str = "classic", typographer: bool = True, fallback_title: str = "Document") -> str:
    rendered = render(text, typographer=typographer)
    meta_tags = []
    for key in ("author", "description", "date"):
        if key in rendered.meta:
            meta_tags.append(f'<meta name="{key}" content="{html.escape(rendered.meta[key], quote=True)}">\n')
    return TEMPLATE.format(
        lang=html.escape(rendered.meta.get("lang", "en"), quote=True),
        meta="".join(meta_tags),
        title=html.escape(rendered.title or fallback_title),
        css=style_css(style),
        body=rendered.body,
    )


def export_html(doc: "Document", settings: "Settings") -> str:
    fallback = doc.path.stem if doc.path else doc.title
    if not doc.format.markdown:
        body = f"<pre>{html.escape(doc.text)}</pre>"
        return TEMPLATE.format(
            lang="en", meta="", title=html.escape(fallback), css=style_css(settings.export_style), body=body
        )
    return render_html(
        doc.text, style=settings.export_style, typographer=settings.typographer, fallback_title=fallback
    )
