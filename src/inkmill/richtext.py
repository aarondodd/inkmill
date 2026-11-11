"""Styled-source ("rich view") spans for Markdown.

The rich view formats Markdown in the editor without hiding anything: bold
text is bold, italics italic, headings stand out, and the markup characters
are dimmed. Every character stays on screen, so cursor movement, wrapping,
selection and undo work exactly as in the raw view.

Nothing here knows about widgets. :func:`line_spans` takes the document's
lines and returns, per line, ``(start, end, style)`` character ranges where
``end`` may be ``None`` for "to the end of the line". Style names are the
``rich.*`` entries in :func:`inkmill.themes.syntax_theme`.
"""

from __future__ import annotations

import re
from functools import lru_cache

from . import markup

Span = tuple[int, "int | None", str]

MARKER = "rich.marker"

_FENCE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})")
_HR = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_SETEXT = re.compile(r"^\s{0,3}(=+|-+)\s*$")
_FOOTNOTE_DEF = re.compile(r"^(\s{0,3})(\[\^[^\]\s]+\]:)")
_REF_DEF = re.compile(r"^\s{0,3}\[[^\]\n^][^\]\n]*\]:\s*\S.*$")
_QUOTE_PREFIX = re.compile(r"^(\s*>\s?)+")
_TASK = re.compile(r"^(\s*)([-*+])(\s+)(\[[ xX]\])(\s+)")
_BULLET = re.compile(r"^(\s*)([-*+])(\s+)")
_NUMBER = re.compile(r"^(\s*)(\d+[.)])(\s+)")

_ESCAPE = re.compile(r"\\[!-/:-@\[-`{-~]")
_CODE = re.compile(r"(`+)(.+?)(?<!`)\1(?!`)")
_IMAGE_OR_LINK = re.compile(r"(!?\[)([^\]\n]*)(\]\()([^)\n]*)(\))")
_REF_LINK = re.compile(r"(\[)([^\]\n^][^\]\n]*)(\]\[)([^\]\n]*)(\])")
_AUTOLINK = re.compile(r"<(?:https?|ftp|mailto):[^>\s]+>")
_BARE_URL = re.compile(r"\b(?:https?|ftp)://[^\s)>\]]+")
_FOOTNOTE_REF = re.compile(r"\[\^[^\]\s]+\]")
_WIKILINK = re.compile(r"(\[\[)([^\]\n]+)(\]\])")
_BOLD_ITALIC = re.compile(r"(\*\*\*|___)(?=\S)(.+?)(?<=\S)\1")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_STAR_ITALIC = re.compile(r"(?<!\*)(\*)(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)")
_UNDER_ITALIC = re.compile(r"(?<![\w_])(_)(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])")
_STRIKE = re.compile(r"(~~)(?=\S)(.+?)(?<=\S)~~")
_HIGHLIGHT = re.compile(r"(==)(?=\S)(.+?)(?<=\S)==")


def _blank(chars: list[str], start: int, end: int) -> None:
    for i in range(start, end):
        chars[i] = " "


@lru_cache(maxsize=4096)
def inline_spans(text: str) -> tuple[Span, ...]:
    """Spans for inline markup in one line of prose."""
    spans: list[Span] = []
    work = list(text)

    def masked() -> str:
        return "".join(work)

    for m in _ESCAPE.finditer(text):
        spans.append((m.start(), m.start() + 1, MARKER))
        _blank(work, m.start(), m.end())
    for m in _CODE.finditer(masked()):
        tick = len(m.group(1))
        spans.append((m.start(), m.start() + tick, MARKER))
        spans.append((m.start() + tick, m.end() - tick, "rich.code"))
        spans.append((m.end() - tick, m.end(), MARKER))
        _blank(work, m.start(), m.end())
    for m in _WIKILINK.finditer(masked()):
        spans.append((m.start(1), m.end(1), MARKER))
        spans.append((m.start(2), m.end(2), "rich.link"))
        spans.append((m.start(3), m.end(3), MARKER))
        _blank(work, m.start(), m.end())
    for m in _FOOTNOTE_REF.finditer(masked()):
        spans.append((m.start(), m.end(), "rich.footnote"))
        _blank(work, m.start(), m.end())
    for pattern in (_IMAGE_OR_LINK, _REF_LINK):
        for m in pattern.finditer(masked()):
            spans.append((m.start(1), m.end(1), MARKER))
            spans.append((m.start(2), m.end(2), "rich.link"))
            spans.append((m.start(3), m.end(5), "rich.url"))
            # The label may itself hold emphasis; the target may not.
            _blank(work, m.start(1), m.end(1))
            _blank(work, m.start(3), m.end(5))
    for pattern in (_AUTOLINK, _BARE_URL):
        for m in pattern.finditer(masked()):
            spans.append((m.start(), m.end(), "rich.link"))
            _blank(work, m.start(), m.end())
    for pattern, style in (
        (_BOLD_ITALIC, "rich.bold_italic"),
        (_BOLD, "rich.bold"),
        (_STAR_ITALIC, "rich.italic"),
        (_UNDER_ITALIC, "rich.italic"),
        (_STRIKE, "rich.strike"),
        (_HIGHLIGHT, "rich.highlight"),
    ):
        for m in pattern.finditer(masked()):
            width = len(m.group(1))
            spans.append((m.start(), m.start() + width, MARKER))
            spans.append((m.start() + width, m.end() - width, style))
            spans.append((m.end() - width, m.end(), MARKER))
            # Blank the markers only, so emphasis nested inside still matches.
            _blank(work, m.start(), m.start() + width)
            _blank(work, m.end() - width, m.end())
    return tuple(spans)


def _shift(spans: tuple[Span, ...], offset: int) -> list[Span]:
    return [(s + offset, None if e is None else e + offset, name) for s, e, name in spans]


def _table_spans(line: str, header: bool, separator: bool) -> list[Span]:
    if separator:
        return [(0, None, MARKER)]
    spans: list[Span] = []
    in_code = False
    i = 0
    cell_start = None
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            spans.append((i, i + 1, MARKER))
            if cell_start is not None:
                spans.extend(_cell_spans(line, cell_start, i, header))
            cell_start = i + 1
        i += 1
    if cell_start is not None and cell_start < len(line):
        spans.extend(_cell_spans(line, cell_start, len(line), header))
    return spans


def _cell_spans(line: str, start: int, end: int, header: bool) -> list[Span]:
    spans = _shift(inline_spans(line[start:end]), start)
    if header and line[start:end].strip():
        spans.insert(0, (start, end, "rich.table_header"))
    return spans


def _is_paragraph_text(line: str) -> bool:
    if not line.strip():
        return False
    return not (
        markup.HEADING.match(line)
        or _BULLET.match(line)
        or _NUMBER.match(line)
        or _QUOTE_PREFIX.match(line)
        or _FENCE.match(line)
        or markup.TABLE_ROW.match(line)
        or line.startswith("    ")
    )


def _block_line_spans(line: str) -> list[Span]:
    """Spans for a line that is not code, front matter or a table."""
    spans: list[Span] = []
    offset = 0
    rest = line
    style_rest: str | None = None

    quote = _QUOTE_PREFIX.match(rest)
    if quote:
        spans.append((0, quote.end(), MARKER))
        offset = quote.end()
        rest = line[offset:]
        style_rest = "rich.quote"

    heading = markup.HEADING.match(rest)
    if heading:
        level = len(heading.group(2))
        spans.append((offset, offset + heading.end(), MARKER))
        spans.append((offset + heading.end(), None, "rich.h1" if level == 1 else "rich.heading"))
        spans.extend(_shift(inline_spans(rest[heading.end() :]), offset + heading.end()))
        return spans

    footnote = _FOOTNOTE_DEF.match(rest)
    if footnote:
        spans.append((offset + footnote.start(2), offset + footnote.end(2), "rich.footnote"))
        start = footnote.end()
        spans.extend(_shift(inline_spans(rest[start:]), offset + start))
        return spans

    if _REF_DEF.match(rest):
        spans.append((offset, None, "rich.url"))
        return spans

    task = _TASK.match(rest)
    item = task or _BULLET.match(rest) or _NUMBER.match(rest)
    if item:
        marker_end = item.end(2)
        spans.append((offset + item.start(2), offset + marker_end, "rich.list"))
        start = item.end()
        if task:
            spans.append((offset + task.start(4), offset + task.end(4), "rich.list"))
            if task.group(4).lower() == "[x]":
                style_rest = "rich.done"
        offset += start
        rest = rest[start:]

    if style_rest and rest:
        spans.append((offset, None, style_rest))
    spans.extend(_shift(inline_spans(rest), offset))
    return spans


# Line kinds from :func:`line_kinds`. Only these need the whole document;
# everything else is decided by the line's own text.
TEXT = "text"
FRONTMATTER = "frontmatter"
CODE = "code"
RULE = "rule"  # fence lines, horizontal rules, setext underlines
TABLE_HEADER = "table_header"
TABLE_SEPARATOR = "table_separator"
TABLE_ROW = "table_row"
SETEXT_1 = "setext_1"
SETEXT_2 = "setext_2"


def line_kinds(lines: list[str]) -> list[str]:
    """Classify every line by the block it belongs to. One cheap pass."""
    n = len(lines)
    kinds = [TEXT] * n
    i = 0
    if n and lines[0].rstrip() == "---":
        for j in range(1, n):
            if lines[j].rstrip() in ("---", "..."):
                kinds[: j + 1] = [FRONTMATTER] * (j + 1)
                i = j + 1
                break
    prev_blank = True
    while i < n:
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            char = fence.group(2)[0]
            width = len(fence.group(2))
            kinds[i] = RULE
            i += 1
            while i < n:
                close = _FENCE.match(lines[i])
                if close and close.group(2)[0] == char and len(close.group(2)) >= width and not lines[i][close.end() :].strip():
                    kinds[i] = RULE
                    i += 1
                    break
                kinds[i] = CODE
                i += 1
            prev_blank = False
            continue
        if (
            "|" in line
            and markup.TABLE_ROW.match(line)
            and i + 1 < n
            and markup.TABLE_ROW.match(lines[i + 1])
            and _is_separator(lines[i + 1])
        ):
            kinds[i] = TABLE_HEADER
            kinds[i + 1] = TABLE_SEPARATOR
            j = i + 2
            while j < n and markup.TABLE_ROW.match(lines[j]):
                kinds[j] = TABLE_ROW
                j += 1
            i = j
            prev_blank = False
            continue
        if prev_blank and _HR.match(line):
            kinds[i] = RULE
            i += 1
            continue
        if i + 1 < n and _SETEXT.match(lines[i + 1]) and _is_paragraph_text(line):
            kinds[i] = SETEXT_1 if lines[i + 1].strip().startswith("=") else SETEXT_2
            kinds[i + 1] = RULE
            i += 2
            prev_blank = False
            continue
        prev_blank = not line.strip()
        i += 1
    return kinds


@lru_cache(maxsize=16384)
def spans_for(line: str, kind: str) -> tuple[Span, ...]:
    """Rich-view spans for one line of the given kind."""
    if kind == FRONTMATTER:
        return ((0, None, "rich.frontmatter"),)
    if kind == CODE:
        return ((0, None, "rich.code"),)
    if kind in (RULE, TABLE_SEPARATOR):
        return ((0, None, MARKER),)
    if kind in (TABLE_HEADER, TABLE_ROW):
        return tuple(_table_spans(line, kind == TABLE_HEADER, False))
    if kind in (SETEXT_1, SETEXT_2):
        return ((0, None, "rich.h1" if kind == SETEXT_1 else "rich.heading"),) + inline_spans(line)
    if not line.strip():
        return ()
    return tuple(_block_line_spans(line))


def line_spans(lines: list[str]) -> dict[int, list[Span]]:
    """Rich-view spans for every line of a Markdown document."""
    out: dict[int, list[Span]] = {}
    for row, kind in enumerate(line_kinds(lines)):
        spans = spans_for(lines[row], kind)
        if spans:
            out[row] = list(spans)
    return out


def _is_separator(line: str) -> bool:
    cells = markup.split_row(line)
    return bool(cells) and all(markup.TABLE_SEP_CELL.match(c) for c in cells if c) and any(c for c in cells)


# -- tables while typing -------------------------------------------------------


def _cell_starts(line: str) -> list[int]:
    """Column of the first character after each unescaped pipe."""
    starts: list[int] = []
    in_code = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            starts.append(i + 1)
        i += 1
    return starts


def cursor_cell(line: str, column: int) -> tuple[int, int]:
    """(cell index, offset into the cell's stripped text) for ``column``."""
    starts = _cell_starts(line)
    if not starts:
        return 0, column
    cell = 0
    for k, start in enumerate(starts):
        if column >= start:
            cell = k
    start = starts[cell]
    end = starts[cell + 1] - 1 if cell + 1 < len(starts) else len(line)
    raw = line[start:end]
    leading = len(raw) - len(raw.lstrip())
    return cell, max(0, column - start - leading)


def cursor_column(line: str, cell: int, offset: int) -> int:
    """Inverse of :func:`cursor_cell` on a tidied row."""
    starts = _cell_starts(line)
    if not starts:
        return min(offset, len(line))
    cell = min(cell, len(starts) - 1)
    start = starts[cell]
    end = starts[cell + 1] - 1 if cell + 1 < len(starts) else len(line)
    raw = line[start:end]
    leading = len(raw) - len(raw.lstrip())
    return min(start + leading + offset, max(start, end))


def table_needs_tidy(lines: list[str], row: int) -> tuple[int, int, list[str]] | None:
    """If ``row`` is in a table with a separator row that is not tidy, return
    ``(first, last, tidied lines)``; otherwise ``None``."""
    bounds = markup.table_bounds(lines, row)
    if bounds is None:
        return None
    first, last = bounds
    block = lines[first : last + 1]
    if len(block) < 2 or not any(_is_separator(b) for b in block):
        return None
    tidied = markup.tidy_table(block)
    if tidied == block:
        return None
    return first, last, tidied
