"""WordPerfect-style status line: file name left, position right."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Label

ELLIPSIS = "..."


def _tail(text: str, width: int) -> str:
    """The longest suffix of ``text`` that fits in ``width`` cells."""
    out: list[str] = []
    used = 0
    for ch in reversed(text):
        w = cell_len(ch)
        if used + w > width:
            break
        out.append(ch)
        used += w
    return "".join(reversed(out))


def _head(text: str, width: int) -> str:
    """The longest prefix of ``text`` that fits in ``width`` cells."""
    out: list[str] = []
    used = 0
    for ch in text:
        w = cell_len(ch)
        if used + w > width:
            break
        out.append(ch)
        used += w
    return "".join(out)


def clip_path(text: str, width: int) -> str:
    """Fit a path into ``width`` cells by dropping its start, not its end.

    Leading folders go first, whole, so ``~/a/b/c/name.md *`` becomes
    ``.../c/name.md *``. If the last segment alone is too long, it is cut
    from the left too, so the end of the file name stays visible.
    """
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return text
    if width <= len(ELLIPSIS):
        return _tail(text, width)
    # Windows paths outside the home folder keep their backslashes.
    sep = "\\" if "\\" in text and "/" not in text else "/"
    parts = text.split(sep)
    for i in range(1, len(parts)):
        candidate = ELLIPSIS + sep + sep.join(parts[i:])
        if cell_len(candidate) <= width:
            return candidate
    return ELLIPSIS + _tail(text, width - len(ELLIPSIS))


# A path clipped to fewer cells than this says too little to be worth showing
# beside a title.
MIN_PATH = 12


def _fit(text: str, width: int) -> str:
    if cell_len(text) <= width:
        return text
    return _head(text, width - len(ELLIPSIS)).rstrip() + ELLIPSIS if width > len(ELLIPSIS) else _head(text, width)


def fit_title(title: str, path: str, width: int) -> tuple[str, str]:
    """Split ``width`` between a document title and its path.

    The title keeps its full length while both fit; otherwise it gets the
    room the path leaves, but never less than half the line, and is cut on
    the right. The path then clips from the left as usual. When fewer than
    ``MIN_PATH`` cells would be left for the path, only the title shows,
    keeping the unsaved marker.
    """
    if not title:
        return "", clip_path(path, width)
    gap = 2
    marker = " *" if path.endswith(" *") else ""
    room = max(width // 2, width - cell_len(path) - gap)
    fitted = _fit(title, room)
    rest = width - cell_len(fitted) - gap
    if rest < MIN_PATH:
        return _fit(title, width - len(marker)) + marker, ""
    return fitted, clip_path(path, rest)


class PathLabel(Widget):
    """A one-line label that clips a path from the left, after an optional title.

    Flash messages are prose, so they clip from the right like a Label.
    """

    DEFAULT_CSS = "PathLabel { height: 1; }"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = ""
        self._title = ""
        self._path_mode = True

    def update(self, text: str, *, path: bool = True, title: str = "") -> None:
        self._text = text
        self._title = title if path else ""
        self._path_mode = path
        self.refresh()

    @property
    def text(self) -> str:
        return self._text

    def render(self) -> Text:
        width = self.content_size.width
        if self._path_mode:
            title, path = fit_title(self._title, self._text, width)
            if not title:
                return Text(path, no_wrap=True)
            out = Text(title, style="bold", no_wrap=True)
            if path:
                out.append("  " + path)
            return out
        return Text(self._text, no_wrap=True, overflow="ellipsis")


class StatusBar(Horizontal):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: bottom;
        background: $im-status-bg;
        color: $im-status-fg;
        padding: 0 1;
    }
    StatusBar > #status-left { width: 1fr; height: 1; margin-right: 2; }
    StatusBar > #status-right { width: auto; height: 1; text-wrap: nowrap; }
    StatusBar.-message > #status-left { color: $im-heading; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._left = ""
        self._title = ""
        self._message_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield PathLabel(id="status-left")
        yield Label("", id="status-right")

    def set_left(self, text: str, title: str = "") -> None:
        self._left = text
        self._title = title
        if self._message_timer is None:
            self.query_one("#status-left", PathLabel).update(text, title=title)

    def set_right(self, text: str) -> None:
        self.query_one("#status-right", Label).update(text)

    def flash(self, message: str, seconds: float = 4.0) -> None:
        if self._message_timer is not None:
            self._message_timer.stop()
        self.add_class("-message")
        self.query_one("#status-left", PathLabel).update(message, path=False)
        self._message_timer = self.set_timer(seconds, self._clear_message)

    def clear_flash(self) -> None:
        if self._message_timer is not None:
            self._message_timer.stop()
        self._clear_message()

    def _clear_message(self) -> None:
        self._message_timer = None
        self.remove_class("-message")
        self.query_one("#status-left", PathLabel).update(self._left, title=self._title)
