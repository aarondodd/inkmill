"""Markdown parsing shared by every renderer.

The parser is markdown-it-py configured for GitHub Flavored Markdown plus the
common extensions writers reach for: footnotes, tables, task lists,
strikethrough, autolinks, GitHub alerts (``> [!NOTE]``), definition lists,
YAML front matter and stable heading anchors.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.gfm import gfm_plugin

_FM_LINE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$")


def _highlight(code: str, lang: str, _attrs: str) -> str:
    if not lang:
        return ""
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name
        from pygments.util import ClassNotFound
    except ImportError:
        return ""
    try:
        lexer = get_lexer_by_name(lang)
    except ClassNotFound:
        return ""
    inner = highlight(code, lexer, HtmlFormatter(nowrap=True))
    # Starting with "<pre" tells markdown-it to use this markup verbatim.
    return f'<pre class="highlight"><code class="language-{html.escape(lang, quote=True)}">{inner}</code></pre>\n'


# Parser extensions registered by plugins, by name, applied after the
# built-in ones. A function receives the MarkdownIt instance and may call
# md.use(...), add rules or change renderer rules.
_EXTENSIONS: dict[str, Callable[[MarkdownIt], None]] = {}


def register_extension(name: str, extend: Callable[[MarkdownIt], None]) -> None:
    _EXTENSIONS[name] = extend
    build_parser.cache_clear()


def clear_extensions() -> None:
    _EXTENSIONS.clear()
    build_parser.cache_clear()


@lru_cache(maxsize=4)
def build_parser(typographer: bool = True) -> MarkdownIt:
    md = MarkdownIt(
        "commonmark",
        {"typographer": typographer, "html": True, "highlight": _highlight},
    )
    if typographer:
        md.enable(["replacements", "smartquotes"])
    md.use(gfm_plugin, front_matter=True)
    md.use(deflist_plugin)
    md.use(anchors_plugin, max_level=6, permalink=False)
    for extend in list(_EXTENSIONS.values()):
        try:
            extend(md)
        except Exception:  # a broken plugin must not break every export
            pass
    return md


@dataclass
class Rendered:
    body: str
    title: str | None = None
    meta: dict[str, str] = field(default_factory=dict)


def parse_front_matter(raw: str) -> dict[str, str]:
    """Read flat ``key: value`` pairs. Nested YAML is ignored on purpose."""
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        match = _FM_LINE.match(line)
        if match and match.group(2):
            meta[match.group(1).lower()] = match.group(2).strip().strip("\"'")
    return meta


def render(text: str, *, typographer: bool = True) -> Rendered:
    md = build_parser(typographer)
    tokens = md.parse(text)
    meta: dict[str, str] = {}
    title: str | None = None
    for i, token in enumerate(tokens):
        if token.type == "front_matter":
            meta = parse_front_matter(token.content)
        elif title is None and token.type == "heading_open" and token.tag == "h1":
            inline = tokens[i + 1]
            title = "".join(
                child.content for child in (inline.children or []) if child.type in ("text", "code_inline")
            )
    body = md.renderer.render(tokens, md.options, {})
    return Rendered(body=body, title=meta.get("title") or title, meta=meta)
