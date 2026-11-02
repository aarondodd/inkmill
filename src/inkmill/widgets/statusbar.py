"""WordPerfect-style status line: file name left, position right."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.timer import Timer
from textual.widgets import Label


class StatusBar(Horizontal):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: bottom;
        background: $im-status-bg;
        color: $im-status-fg;
        padding: 0 1;
    }
    StatusBar > #status-left { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    StatusBar > #status-right { width: auto; height: 1; text-wrap: nowrap; }
    StatusBar.-message > #status-left { color: $im-heading; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._left = ""
        self._message_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Label("", id="status-left")
        yield Label("", id="status-right")

    def set_left(self, text: str) -> None:
        self._left = text
        if self._message_timer is None:
            self.query_one("#status-left", Label).update(text)

    def set_right(self, text: str) -> None:
        self.query_one("#status-right", Label).update(text)

    def flash(self, message: str, seconds: float = 4.0) -> None:
        if self._message_timer is not None:
            self._message_timer.stop()
        self.add_class("-message")
        self.query_one("#status-left", Label).update(message)
        self._message_timer = self.set_timer(seconds, self._clear_message)

    def _clear_message(self) -> None:
        self._message_timer = None
        self.remove_class("-message")
        self.query_one("#status-left", Label).update(self._left)
