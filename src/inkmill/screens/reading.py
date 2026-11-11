"""Reading view: the current document fully formatted, read-only.

Built on Textual's Markdown widget, so headings, emphasis, lists, quotes,
code blocks and tables are drawn as formatted text rather than as markup.
The source is adjusted first for things that widget does not know:
front matter is hidden, footnote references become superscripts, and task
list boxes are kept as [x] and [ ]. Line numbers are kept, so the view can open
at the paragraph the cursor is in.
"""

from __future__ import annotations

import re

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Label, Markdown
from textual.widgets._markdown import MarkdownBlock

_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_FOOTNOTE_DEF = re.compile(r"^(\s{0,3})\[\^([^\]\s]+)\]:\s?(.*)$")
_FOOTNOTE_REF = re.compile(r"\[\^([^\]\s]+)\]")
_TASK = re.compile(r"^(\s*[-*+]\s+)\[([ xX])\](\s+)")
_CODE_SPAN = re.compile(r"(`+).+?(?<!`)\1(?!`)")


def _note_label(label: str) -> str:
    return label.translate(_SUPERSCRIPT) if label.isdigit() else f"[{label}]"


def _replace_refs(line: str) -> str:
    # Leave footnote-like text inside code spans alone.
    parts: list[str] = []
    last = 0
    for m in _CODE_SPAN.finditer(line):
        parts.append(_FOOTNOTE_REF.sub(lambda r: _note_label(r.group(1)), line[last : m.start()]))
        parts.append(m.group(0))
        last = m.end()
    parts.append(_FOOTNOTE_REF.sub(lambda r: _note_label(r.group(1)), line[last:]))
    return "".join(parts)


def reading_text(text: str) -> str:
    """``text`` adjusted for the reading view, with the same line count."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    if lines and lines[0].rstrip() == "---":
        for j in range(1, len(lines)):
            if lines[j].rstrip() in ("---", "..."):
                out.extend([""] * (j + 1))
                i = j + 1
                break
    fence: str | None = None
    notes: list[int] = []
    for line in lines[i:]:
        m = _FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append(line)
            continue
        if m:
            fence = m.group(1)
            out.append(line)
            continue
        definition = _FOOTNOTE_DEF.match(line)
        if definition:
            indent, label, body = definition.groups()
            # Consecutive notes form one paragraph; a trailing backslash on
            # the previous note is a hard line break that keeps each on its
            # own line. The last note gets none, or it would show.
            if notes and notes[-1] == len(out) - 1:
                out[-1] += "\\"
            notes.append(len(out))
            out.append(f"{indent}{_note_label(label)} {_replace_refs(body)}")
            continue
        task = _TASK.match(line)
        if task:
            # Plain brackets: check-box glyphs are missing from many terminal
            # fonts (DOS and bitmap fonts show an empty box instead).
            box = "[x]" if task.group(2).lower() == "x" else "[ ]"
            line = f"{task.group(1)}{box}{task.group(3)}{line[task.end():]}"
        out.append(_replace_refs(line))
    return "\n".join(out)


class ReadingScreen(Screen):
    """Dismisses with nothing; Esc, Q or the toggle key return to editing."""

    DEFAULT_CSS = """
    ReadingScreen { background: $background; color: $foreground; }
    ReadingScreen > #reading-scroll { height: 1fr; align-horizontal: center; padding: 0 1; }
    ReadingScreen Markdown { width: 100%; background: $background; margin: 0; padding: 0; }
    ReadingScreen MarkdownBlock > .strong { color: $im-bold; }
    ReadingScreen MarkdownBlock > .em { color: $im-italic; }
    ReadingScreen.-plain-emphasis MarkdownBlock > .strong { color: $foreground; }
    ReadingScreen.-plain-emphasis MarkdownBlock > .em { color: $foreground; }
    ReadingScreen > #reading-hint {
        dock: bottom; height: 1; width: 100%; padding: 0 1;
        background: $im-status-bg; color: $im-status-fg; text-wrap: nowrap; text-overflow: ellipsis;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Back to editing", show=False),
        Binding("q", "close", show=False),
    ]

    def __init__(
        self,
        text: str,
        *,
        title: str = "",
        row: int = 0,
        width: int = 0,
        close_keys: tuple[str, ...] = (),
        emphasis_colors: bool = True,
    ) -> None:
        super().__init__()
        self.set_class(not emphasis_colors, "-plain-emphasis")
        self._text = reading_text(text)
        self._title = title
        self._row = row
        self._width = width
        self._close_keys = close_keys

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="reading-scroll"):
            yield Markdown(id="reading-doc", open_links=False)
        hint = f"Reading view: {self._title}  |  Esc back to editing  |  Up/Down, PgUp/PgDn scroll"
        yield Label(hint, id="reading-hint")

    async def on_mount(self) -> None:
        markdown = self.query_one("#reading-doc", Markdown)
        if self._width > 0:
            markdown.styles.max_width = self._width
        await markdown.update(self._text)
        scroll = self.query_one("#reading-scroll", VerticalScroll)
        scroll.focus()
        self.call_after_refresh(self.scroll_to_row, self._row)

    def block_for_row(self, row: int) -> MarkdownBlock | None:
        """The innermost block whose source lines include ``row``, or the last
        block that starts before it."""
        best: MarkdownBlock | None = None
        best_span = None
        before: MarkdownBlock | None = None
        for block in self.query(MarkdownBlock):
            start, end = block.source_range
            if end <= start:
                continue
            if start <= row < end and (best_span is None or end - start <= best_span):
                best, best_span = block, end - start
            if start <= row:
                before = block
        return best or before

    def scroll_to_row(self, row: int) -> None:
        block = self.block_for_row(row)
        if block is not None and row > 0:
            self.query_one("#reading-scroll", VerticalScroll).scroll_to_widget(block, top=True, animate=False)

    def on_key(self, event) -> None:
        if event.key in self._close_keys:
            event.stop()
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        href = event.href
        if re.match(r"^(https?|ftp|mailto):", href):
            from ..system import open_url

            try:
                open_url(href)
            except RuntimeError as exc:
                self.notify(str(exc), severity="warning")
        else:
            self.notify(f"Link: {href}", timeout=4)
