"""The Binder outline: every chapter with its status, words and synopsis.

A corkboard as a table. Enter opens a chapter; ``[`` and ``]`` move it;
S sets its status, Y its synopsis and T its word target.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Label, Static

from inkmill.documents import count_words
from inkmill.screens.dialogs import ChoiceDialog, InputDialog
from inkmill.screens.files import FileTable

from . import model


class BinderOutlineScreen(Screen):
    """Dismisses with a chapter path to open, or None."""

    DEFAULT_CSS = """
    BinderOutlineScreen { background: $background; color: $foreground; }
    #bo-header { height: 1; padding: 0 1; }
    #bo-title { width: 1fr; text-style: bold; }
    #bo-mode { width: auto; color: $im-dim; }
    #bo-table { height: 1fr; border: solid $im-dim; }
    #bo-synopsis { height: auto; max-height: 6; padding: 0 1; color: $im-dim; }
    #bo-totals { height: 1; padding: 0 1; }
    #bo-options { height: auto; padding: 0 1; background: $im-status-bg; color: $im-status-fg; }
    """

    BINDINGS = [Binding("escape", "close", show=False)]

    def __init__(self, binder: Path, read, write, statuses: list[str], pace) -> None:
        super().__init__()
        self.binder = binder
        self.read = read
        self.write = write
        self.statuses = statuses
        self.pace = pace
        self.chapters: list[Path] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="bo-header"):
            yield Label("", id="bo-title")
            yield Label("Binder Outline", id="bo-mode")
        yield FileTable(cursor_type="row", zebra_stripes=False, id="bo-table")
        yield Static("", id="bo-synopsis")
        yield Label("", id="bo-totals")
        options = Text()
        for i, item in enumerate(["Enter Open", "[ ] Move", "S Status", "Y Synopsis", "T Target", "Esc Close"]):
            key, _, label = item.partition(" ")
            if i:
                options.append("; ")
            options.append(key, style="bold")
            options.append(" " + label)
        yield Static(options, id="bo-options")

    def on_mount(self) -> None:
        table = self.query_one(FileTable)
        for key, label in (("n", "#"), ("title", "Chapter"), ("status", "Status"), ("words", "Words"), ("target", "Target"), ("synopsis", "Synopsis")):
            table.add_column(label, key=key)
        self.refresh_table()
        table.focus()

    def refresh_table(self, keep: int | None = None) -> None:
        table = self.query_one(FileTable)
        binder_text = self.read(self.binder) or ""
        links = model.read_links(self.binder, binder_text)
        self.query_one("#bo-title", Label).update(links.title)
        row = keep if keep is not None else table.cursor_row
        self.chapters = list(links.contents)
        table.clear()
        total = 0
        for i, path in enumerate(self.chapters, start=1):
            text = self.read(path)
            words = count_words(text or "")
            total += words
            target = model.field_value(text, "target")
            synopsis = model.field_value(text, "synopsis").replace("\n", " ")
            status = model.field_value(text, "status")
            title = Text(model.title_of(path, text), style="" if text is not None else "italic")
            if text is None:
                title.append(" (missing)")
            words_cell = Text(f"{words:,}", justify="right")
            if target.isdigit() and words >= int(target):
                words_cell.stylize("bold")
            table.add_row(
                str(i), title, status or "-", words_cell, Text(f"{int(target):,}" if target.isdigit() else "-", justify="right"),
                synopsis[:60] + ("..." if len(synopsis) > 60 else ""), key=str(path),
            )
        target = model.field_value(binder_text, "target").replace(",", "")
        deadline = model.field_value(binder_text, "deadline")
        line = f"{len(self.chapters)} chapter(s), {total:,} words"
        if target.isdigit():
            line += f" of {int(target):,} ({min(100, round(100 * total / int(target)))}%)"
            timing = self.pace(total, int(target), deadline)
            if timing:
                line += f"; {timing}"
        self.query_one("#bo-totals", Label).update(line)
        if self.chapters and row is not None:
            table.move_cursor(row=min(row, len(self.chapters) - 1))
        self.show_synopsis()

    def current(self) -> Path | None:
        table = self.query_one(FileTable)
        if not self.chapters or table.cursor_row is None:
            return None
        return self.chapters[min(table.cursor_row, len(self.chapters) - 1)]

    def show_synopsis(self) -> None:
        path = self.current()
        synopsis = model.field_value(self.read(path), "synopsis") if path else ""
        self.query_one("#bo-synopsis", Static).update(synopsis or "No synopsis yet. Y adds one.")

    def on_data_table_row_highlighted(self, _event) -> None:
        self.show_synopsis()

    def on_data_table_row_selected(self, _event) -> None:
        path = self.current()
        if path is not None:
            self.dismiss(str(path))

    def on_key(self, event: events.Key) -> None:
        key = event.character or ""
        actions = {"[": lambda: self.move(-1), "]": lambda: self.move(1),
                   "s": self.edit_status, "S": self.edit_status, "y": self.edit_synopsis, "Y": self.edit_synopsis,
                   "t": self.edit_target, "T": self.edit_target}
        if key in actions:
            event.stop()
            actions[key]()

    def move(self, step: int) -> None:
        path = self.current()
        if path is None:
            return
        text = self.read(self.binder) or ""
        updated = model.move_in_contents(text, self.binder, path, step)
        if updated != text:
            self.write(self.binder, updated)
            table = self.query_one(FileTable)
            self.refresh_table(keep=(table.cursor_row or 0) + step)

    def _set(self, path: Path, key: str, value: str | None) -> None:
        text = self.read(path)
        if text is None:
            self.notify(f"{path.name} is missing.", severity="warning")
            return
        self.write(path, model.set_field(text, key, value))
        self.refresh_table()

    @work(exclusive=True)
    async def edit_status(self) -> None:
        path = self.current()
        if path is None:
            return
        current = model.field_value(self.read(path), "status")
        items = [(s, s) for s in self.statuses] + [("", "(none)")]
        choice = await self.app.push_screen_wait(ChoiceDialog(f"Status: {path.name}", items, current))
        if choice is not None:
            self._set(path, "status", choice or None)

    @work(exclusive=True)
    async def edit_synopsis(self) -> None:
        path = self.current()
        if path is None:
            return
        current = model.field_value(self.read(path), "synopsis")
        answer = await self.app.push_screen_wait(InputDialog(f"Synopsis: {path.name}", "One or two sentences:", current))
        if answer is not None:
            self._set(path, "synopsis", answer.strip() or None)

    @work(exclusive=True)
    async def edit_target(self) -> None:
        path = self.current()
        if path is None:
            return
        current = model.field_value(self.read(path), "target")
        answer = await self.app.push_screen_wait(InputDialog(f"Word target: {path.name}", "Words (blank for none):", current))
        if answer is not None:
            value = answer.strip().replace(",", "")
            if value and not value.isdigit():
                self.notify("A target is a number of words.", severity="warning")
                return
            self._set(path, "target", value or None)

    def action_close(self) -> None:
        self.dismiss(None)
