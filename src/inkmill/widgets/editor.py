"""The writing surface: a TextArea with Markdown editing operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual._tree_sitter import TREE_SITTER
from textual.widgets import TextArea
from textual.widgets.text_area import Selection

from .. import markup

if TYPE_CHECKING:
    from ..documents import Document

Location = tuple[int, int]


class InkEditor(TextArea):
    """One editor per open document, so each keeps its own undo history."""

    DEFAULT_CSS = """
    InkEditor {
        border: none;
        padding: 0 1;
        background: $background;
        color: $foreground;
        height: 1fr;
    }
    InkEditor:focus { border: none; }
    InkEditor > .text-area--cursor-line { background: transparent; }
    InkEditor > .text-area--selection { background: $im-select-bg; color: $im-select-fg; }
    InkEditor > .text-area--cursor { background: $im-cursor-bg; color: $im-cursor-fg; }
    InkEditor > .text-area--matching-bracket { background: transparent; }
    """

    # TextArea's own bindings for these keys (F6 select line, F7 select all,
    # Ctrl+W delete word, ...) are superseded by app commands, which are bound
    # with priority. Nothing to declare here.

    def __init__(self, document: "Document", *, soft_wrap: bool = True, highlight: bool = True) -> None:
        language = None
        if highlight and TREE_SITTER and document.format.language:
            language = document.format.language
        super().__init__(
            document.text,
            language=language,
            soft_wrap=soft_wrap,
            tab_behavior="indent",
            show_line_numbers=False,
            highlight_cursor_line=False,
            id=f"doc-{document.id}",
        )
        self.doc = document
        self.indent_type = "spaces"
        self.indent_width = 4
        self.return_stack: list[Location] = []

    def apply_syntax_theme(self, theme) -> None:
        from ..themes import syntax_theme

        self.register_theme(syntax_theme(theme))
        self.theme = "inkmill"

    # -- offsets ---------------------------------------------------------

    def index_of(self, location: Location) -> int:
        return self.document.get_index_from_location(location)

    def location_of(self, index: int) -> Location:
        return self.document.get_location_from_index(index)

    def select_range(self, start: Location, end: Location) -> None:
        self.selection = Selection(start, end)
        self.scroll_cursor_visible(center=True)

    # -- inline markup -----------------------------------------------------

    def toggle_wrap(self, left: str, right: str | None = None) -> None:
        """Wrap or unwrap the selection with ``left``/``right`` markers."""
        right = left if right is None else right
        start, end = sorted(self.selection)
        selected = self.get_text_range(start, end)
        if not selected:
            # Unwrap if the cursor sits inside an empty pair, else insert one.
            row, col = start
            line = self.document.get_line(row)
            if line[max(0, col - len(left)) : col] == left and line[col : col + len(right)] == right:
                self.replace("", (row, col - len(left)), (row, col + len(right)))
                return
            self.insert(left + right, start)
            self.move_cursor((row, col + len(left)))
            return
        if selected.startswith(left) and selected.endswith(right) and len(selected) >= len(left) + len(right):
            inner = selected[len(left) : len(selected) - len(right)]
            result = self.replace(inner, start, end)
            self.selection = Selection(start, result.end_location)
            return
        s_idx, e_idx = self.index_of(start), self.index_of(end)
        text = self.text
        if text[max(0, s_idx - len(left)) : s_idx] == left and text[e_idx : e_idx + len(right)] == right:
            outer_start = self.location_of(s_idx - len(left))
            outer_end = self.location_of(e_idx + len(right))
            result = self.replace(selected, outer_start, outer_end)
            self.selection = Selection(outer_start, result.end_location)
            return
        result = self.replace(left + selected + right, start, end)
        inner_start = self.location_of(s_idx + len(left))
        self.selection = Selection(inner_start, self.location_of(s_idx + len(left) + len(selected)))

    # -- block markup ------------------------------------------------------

    def selected_rows(self) -> tuple[int, int]:
        start, end = sorted(self.selection)
        last = end[0]
        if end[1] == 0 and end[0] > start[0]:
            last -= 1
        return start[0], last

    def _replace_rows(self, first: int, last: int, new_lines: list[str]) -> None:
        end_col = len(self.document.get_line(last))
        old_cursor = self.cursor_location
        self.replace("\n".join(new_lines), (first, 0), (last, end_col))
        if first == last:
            row = first
            delta = len(new_lines[0]) - end_col
            self.move_cursor((row, max(0, old_cursor[1] + delta)))
        else:
            self.selection = Selection((first, 0), (first + len(new_lines) - 1, len(new_lines[-1])))

    def set_heading(self, level: int) -> None:
        first, last = self.selected_rows()
        lines = [markup.set_heading(self.document.get_line(r), level) for r in range(first, last + 1)]
        self._replace_rows(first, last, lines)

    def toggle_block(self, kind: str) -> None:
        first, last = self.selected_rows()
        lines = [self.document.get_line(r) for r in range(first, last + 1)]
        self._replace_rows(first, last, markup.toggle_prefix(lines, kind))

    def toggle_task_done(self) -> None:
        first, last = self.selected_rows()
        lines = [markup.toggle_task_done(self.document.get_line(r)) for r in range(first, last + 1)]
        self._replace_rows(first, last, lines)

    def insert_block(self, lines: list[str]) -> None:
        """Insert lines as their own paragraph after the current line."""
        row = self.cursor_location[0]
        current = self.document.get_line(row)
        prefix = "\n\n" if current.strip() else ""
        if not current.strip() and row > 0 and self.document.get_line(row - 1).strip():
            prefix = "\n"
        location = (row, len(current))
        self.insert(prefix + "\n".join(lines) + "\n", location)
        first_row = row + prefix.count("\n")
        self.move_cursor((first_row, 0))

    def insert_link(self, text: str, url: str) -> None:
        start, end = sorted(self.selection)
        label = self.get_text_range(start, end) or text or url
        self.replace(f"[{label}]({url})", start, end)

    def insert_footnote(self) -> int:
        """Insert the next numbered footnote reference and its definition.

        The cursor moves to the definition; :meth:`go_back` returns to the
        reference.
        """
        number = markup.next_footnote_number(self.text)
        ref = f"[^{number}]"
        start, end = sorted(self.selection)
        result = self.replace(ref, start, end)
        self.return_stack.append(result.end_location)
        body = self.text.rstrip("\n")
        last_line = body.rsplit("\n", 1)[-1]
        # Keep consecutive definitions together; otherwise start a new block.
        sep = "\n" if markup.FOOTNOTE_DEF.match(last_line) else "\n\n"
        self.replace(f"{sep}{ref}: ", self.location_of(len(body)), self.document.end)
        self.move_cursor(self.document.end)
        self.scroll_cursor_visible(center=True)
        return number

    def go_back(self) -> bool:
        if not self.return_stack:
            return False
        loc = self.return_stack.pop()
        row = min(loc[0], self.document.line_count - 1)
        col = min(loc[1], len(self.document.get_line(row)))
        self.move_cursor((row, col))
        self.scroll_cursor_visible(center=True)
        return True

    def tidy_table(self) -> bool:
        lines = self.document.lines
        bounds = markup.table_bounds(lines, self.cursor_location[0])
        if bounds is None:
            return False
        first, last = bounds
        new = markup.tidy_table(lines[first : last + 1])
        row, _ = self.cursor_location
        self.replace("\n".join(new), (first, 0), (last, len(lines[last])))
        self.move_cursor((row, min(2, len(new[row - first]))))
        return True

    # -- search ------------------------------------------------------------

    def find(self, needle: str, *, forward: bool = True, case: bool = False, regex: bool = False) -> bool:
        matches = markup.find_all(self.text, needle, case=case, regex=regex)
        if not matches:
            return False
        start, end = sorted(self.selection)
        if forward:
            pos = self.index_of(end)
            match = next((m for m in matches if m[0] >= pos), matches[0])
        else:
            pos = self.index_of(start)
            match = next((m for m in reversed(matches) if m[0] < pos), matches[-1])
        self.select_range(self.location_of(match[0]), self.location_of(match[1]))
        return True

    def replace_all(self, needle: str, replacement: str, *, case: bool = False, regex: bool = False) -> int:
        matches = markup.find_all(self.text, needle, case=case, regex=regex)
        if not matches:
            return 0
        import re

        flags = 0 if case else re.IGNORECASE
        pattern = re.compile(needle if regex else re.escape(needle), flags)
        new_text = pattern.sub(replacement if regex else replacement.replace("\\", "\\\\"), self.text)
        cursor = self.cursor_location
        self.replace(new_text, self.document.start, self.document.end)
        row = min(cursor[0], self.document.line_count - 1)
        self.move_cursor((row, min(cursor[1], len(self.document.get_line(row)))))
        return len(matches)

    def replace_selection_if_match(self, needle: str, replacement: str, *, case: bool = False) -> bool:
        start, end = sorted(self.selection)
        selected = self.get_text_range(start, end)
        if selected and (selected == needle if case else selected.lower() == needle.lower()):
            self.replace(replacement, start, end)
            return True
        return False
