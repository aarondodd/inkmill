"""List Files: the WordPerfect F5 file manager.

Browse directories with a live preview of the highlighted file ("Look"),
mark several files to open at once, and copy, move, rename or delete without
leaving the editor. The same screen doubles as the Save As dialog.

Numbered options mirror WordPerfect 5.1's List Files line; letter keys work too.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rich.markdown import Markdown
from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Input, Label, Static

from .dialogs import ConfirmDialog, InputDialog

if TYPE_CHECKING:
    from ..app import InkmillApp

PREVIEW_BYTES = 128 * 1024
SORTS = ("name", "modified", "size")


@dataclass
class Entry:
    path: Path
    is_dir: bool
    size: int
    mtime: float
    label: str | None = None  # For "." and "..".

    @property
    def name(self) -> str:
        return self.label or self.path.name


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024 or unit == "T":
            return f"{size:,.0f}{unit}" if unit == "B" else f"{size:,.1f}{unit}"
        size /= 1024
    return f"{n}B"


def is_hidden(path: Path, st: os.stat_result | None = None) -> bool:
    if path.name.startswith("."):
        return True
    if sys.platform == "win32" and st is not None:
        return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_HIDDEN)
    return False


def list_directory(
    directory: Path,
    *,
    show_hidden: bool = False,
    extensions: set[str] | None = None,
    sort: str = "name",
    name_filter: str = "",
) -> list[Entry]:
    entries: list[Entry] = []
    with os.scandir(directory) as it:
        for item in it:
            path = Path(item.path)
            try:
                st = item.stat()
                is_dir = item.is_dir()
            except OSError:
                continue
            if not show_hidden and is_hidden(path, st):
                continue
            if name_filter and name_filter.lower() not in item.name.lower():
                continue
            if not is_dir and extensions is not None and path.suffix.lower() not in extensions:
                continue
            entries.append(Entry(path, is_dir, 0 if is_dir else st.st_size, st.st_mtime))
    key = {
        "name": lambda e: e.name.lower(),
        "modified": lambda e: -e.mtime,
        "size": lambda e: -e.size,
    }[sort]
    dirs = sorted((e for e in entries if e.is_dir), key=lambda e: e.name.lower())
    files = sorted((e for e in entries if not e.is_dir), key=key)
    return dirs + files


def strip_front_matter(text: str) -> str:
    """Drop a leading YAML block so the rendered preview starts at the prose."""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[end + 4 :].lstrip("\n")
    return text


def read_preview(path: Path) -> tuple[str, bool]:
    """Return (text, truncated). Raises ValueError for binary files."""
    with open(path, "rb") as fh:
        data = fh.read(PREVIEW_BYTES + 1)
    truncated = len(data) > PREVIEW_BYTES
    data = data[:PREVIEW_BYTES]
    if b"\0" in data:
        raise ValueError("binary file")
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n"), truncated


class FileTable(DataTable):
    DEFAULT_CSS = """
    FileTable {
        background: $background;
        color: $foreground;
        height: 1fr;
        scrollbar-size-vertical: 1;
    }
    FileTable > .datatable--header { background: $background; color: $im-dim; text-style: bold; }
    FileTable > .datatable--cursor,
    FileTable:focus > .datatable--cursor { background: $im-select-bg; color: $im-select-fg; text-style: none; }
    FileTable > .datatable--hover { background: transparent; }
    FileTable:focus { background-tint: transparent; }
    """


class FileManagerScreen(Screen):
    """Dismisses with ``list[Path]`` in open mode, ``Path`` in save mode."""

    DEFAULT_CSS = """
    FileManagerScreen { background: $background; color: $foreground; }
    #fm-header { height: 1; padding: 0 1; background: $background; }
    #fm-dir { width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    #fm-mode { width: auto; color: $im-dim; }
    #fm-body { height: 1fr; }
    #fm-list-pane { width: 11fr; border: solid $im-dim; }
    #fm-preview-pane { width: 9fr; border: solid $im-dim; padding: 0 1; }
    #fm-preview-pane.-hidden { display: none; }
    FileManagerScreen.-look #fm-list-pane { display: none; }
    FileManagerScreen.-look #fm-preview-pane { display: block; }
    #fm-preview-title { color: $im-heading; height: 1; margin-bottom: 1; }
    #fm-info { height: 1; padding: 0 1; color: $im-dim; }
    #fm-options { height: auto; padding: 0 1; background: $im-status-bg; color: $im-status-fg; }
    #fm-name-row, #fm-search-row { height: 1; padding: 0 1; display: none; }
    #fm-name-row.-visible, #fm-search-row.-visible { display: block; }
    #fm-name-row Label, #fm-search-row Label { width: auto; margin-right: 1; }
    #fm-name-row Input, #fm-search-row Input {
        border: none; height: 1; padding: 0 1; width: 1fr;
        background: $im-input-bg; color: $im-input-fg;
    }
    #fm-name-row Input:focus, #fm-search-row Input:focus { border: none; background-tint: transparent; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("backspace", "parent", show=False),
        Binding("tab", "toggle_focus", show=False),
    ]

    def __init__(
        self,
        mode: Literal["open", "save"] = "open",
        directory: Path | None = None,
        filename: str = "",
    ) -> None:
        super().__init__()
        self.mode = mode
        self.directory = (directory or Path.cwd()).resolve()
        self.filename = filename
        self.entries: list[Entry] = []
        self.marked: set[Path] = set()
        self.show_hidden = False
        self.documents_only = False
        self.sort = "name"
        self.name_filter = ""
        self.rendered_preview = True
        self.preview_path: Path | None = None

    @property
    def inkmill(self) -> "InkmillApp":
        return self.app  # type: ignore[return-value]

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="fm-header"):
            yield Label("", id="fm-dir")
            yield Label("Save As" if self.mode == "save" else "List Files", id="fm-mode")
        with Horizontal(id="fm-body"):
            with Vertical(id="fm-list-pane"):
                yield FileTable(cursor_type="row", zebra_stripes=False, id="fm-table")
            with Vertical(id="fm-preview-pane"):
                yield Label("", id="fm-preview-title")
                with VerticalScroll(id="fm-preview-scroll"):
                    yield Static("", id="fm-preview")
        yield Label("", id="fm-info")
        with Horizontal(id="fm-search-row"):
            yield Label("Name search:")
            yield Input(id="fm-search")
        with Horizontal(id="fm-name-row", classes="-visible" if self.mode == "save" else ""):
            yield Label("Save as:")
            yield Input(self.filename, id="fm-name")
        yield Static(self._options_text(), id="fm-options")

    def _options_text(self) -> Text:
        if self.mode == "save":
            items = ["Enter Save", "5 New Folder", "6 Look", "7 Other Directory", "N Name Search", "Esc Cancel"]
        else:
            items = [
                "1 Open",
                "2 Delete",
                "3 Move/Rename",
                "4 Copy",
                "5 New Folder",
                "6 Look",
                "7 Other Directory",
                "* Mark",
                "N Name Search",
            ]
        extra = ["H Home", ". Hidden", "T Type filter", "S Sort", "Esc Close"]
        text = Text()
        for i, item in enumerate(items + extra):
            key, _, label = item.partition(" ")
            if i:
                text.append("; ")
            text.append(key, style="bold")
            text.append(" " + label)
        return text

    def on_mount(self) -> None:
        table = self.query_one(FileTable)
        table.add_column(" ", key="mark", width=1)
        table.add_column("Name", key="name")
        table.add_column("Size", key="size")
        table.add_column("Modified", key="mtime")
        self.refresh_listing()
        if self.mode == "save":
            self.query_one("#fm-name", Input).focus()
        else:
            table.focus()

    def on_resize(self, event: events.Resize) -> None:
        narrow = event.size.width < 90
        pane = self.query_one("#fm-preview-pane")
        pane.set_class(narrow and not self.has_class("-look"), "-hidden")

    # -- listing -----------------------------------------------------------

    def refresh_listing(self, select: Path | None = None) -> None:
        table = self.query_one(FileTable)
        exts = self.inkmill.formats.document_extensions() if self.documents_only else None
        try:
            entries = list_directory(
                self.directory,
                show_hidden=self.show_hidden,
                extensions=exts,
                sort=self.sort,
                name_filter=self.name_filter,
            )
        except OSError as exc:
            self.notify(f"Cannot read {self.directory}: {exc.strerror or exc}", severity="error")
            entries = []
        parent = self.directory.parent
        head = []
        if parent != self.directory:
            head.append(Entry(parent, True, 0, 0.0, label=".."))
        self.entries = head + entries
        previous = select or self.current_path()
        table.clear()
        name_width = max(12, min(32, max((len(e.name) for e in self.entries), default=12) + 2))
        for entry in self.entries:
            mark = "*" if entry.path in self.marked else " "
            if entry.is_dir:
                name = Text(entry.name + os.sep, style="bold")
                size = Text("<Dir>", justify="right")
            else:
                name = Text(entry.name)
                size = Text(human_size(entry.size), justify="right")
            when = datetime.fromtimestamp(entry.mtime).strftime("%Y-%m-%d %H:%M") if entry.mtime else ""
            name.truncate(name_width, overflow="ellipsis", pad=True)
            table.add_row(mark, name, size, when, key=str(entry.path) + ("|up" if entry.label else ""))
        self._update_header()
        if previous is not None:
            for i, entry in enumerate(self.entries):
                if entry.path == previous and not entry.label:
                    table.move_cursor(row=i)
                    break
        self.update_preview()

    def _update_header(self) -> None:
        label = str(self.directory)
        if self.documents_only:
            label += f"{os.sep}*[{','.join(sorted(self.inkmill.formats.document_extensions()))}]"
        else:
            label += f"{os.sep}*.*"
        self.query_one("#fm-dir", Label).update(f"Directory: {label}")
        try:
            usage = shutil.disk_usage(self.directory)
            free = f"Free: {human_size(usage.free)}"
        except OSError:
            free = ""
        files = sum(1 for e in self.entries if not e.is_dir)
        folders = sum(1 for e in self.entries if e.is_dir and not e.label)
        parts = [free, f"Files: {files}", f"Folders: {folders}", f"Marked: {len(self.marked)}", f"Sort: {self.sort}"]
        if self.name_filter:
            parts.append(f"Filter: {self.name_filter}")
        if self.show_hidden:
            parts.append("Hidden shown")
        self.query_one("#fm-info", Label).update("  ".join(p for p in parts if p))

    def current_entry(self) -> Entry | None:
        table = self.query_one(FileTable)
        if not self.entries or table.cursor_row < 0 or table.cursor_row >= len(self.entries):
            return None
        return self.entries[table.cursor_row]

    def current_path(self) -> Path | None:
        entry = self.current_entry()
        return entry.path if entry and not entry.label else None

    def selected_files(self) -> list[Path]:
        if self.marked:
            return sorted(self.marked)
        entry = self.current_entry()
        if entry and not entry.is_dir:
            return [entry.path]
        return []

    # -- preview -----------------------------------------------------------

    @on(DataTable.RowHighlighted)
    def _row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.update_preview()
        entry = self.current_entry()
        if self.mode == "save" and entry and not entry.is_dir:
            self.query_one("#fm-name", Input).value = entry.name

    def update_preview(self) -> None:
        entry = self.current_entry()
        title = self.query_one("#fm-preview-title", Label)
        body = self.query_one("#fm-preview", Static)
        self.query_one("#fm-preview-scroll").scroll_home(animate=False)
        if entry is None:
            title.update("")
            body.update("")
            return
        if entry.is_dir:
            title.update(f"{entry.name}{os.sep}")
            try:
                children = list_directory(entry.path, show_hidden=self.show_hidden)
                listing = "\n".join(c.name + (os.sep if c.is_dir else "") for c in children[:200])
                body.update(Text(listing or "(empty folder)"))
            except OSError as exc:
                body.update(Text(f"(cannot read: {exc.strerror or exc})"))
            return
        self.preview_path = entry.path
        title.update(f"Look: {entry.name}  ({'rendered' if self._renders(entry.path) else 'text'})")
        self._load_preview(entry.path)

    def _renders(self, path: Path) -> bool:
        fmt = self.inkmill.formats.for_path(path)
        return self.rendered_preview and fmt.markdown

    @work(exclusive=True, thread=True, group="preview")
    def _load_preview(self, path: Path) -> None:
        try:
            text, truncated = read_preview(path)
        except ValueError:
            content: object = Text("(binary file, no preview)")
        except OSError as exc:
            content = Text(f"(cannot read: {exc.strerror or exc})")
        else:
            if truncated:
                text += "\n\n[... preview truncated ...]"
            if self._renders(path):
                content = Markdown(strip_front_matter(text))
            else:
                content = Text(text)
        self.app.call_from_thread(self._show_preview, path, content)

    def _show_preview(self, path: Path, content: object) -> None:
        if path == self.preview_path:
            self.query_one("#fm-preview", Static).update(content)

    # -- actions -------------------------------------------------------------

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        self.activate()

    def activate(self) -> None:
        entry = self.current_entry()
        if entry is None:
            return
        if entry.is_dir:
            self.change_directory(entry.path)
        elif self.mode == "open":
            self.dismiss([entry.path])
        else:
            self.query_one("#fm-name", Input).value = entry.name
            self.save_here()

    def change_directory(self, path: Path) -> None:
        old = self.directory
        try:
            path = path.expanduser().resolve()
            os.listdir(path)
        except OSError as exc:
            self.notify(f"Cannot open {path}: {exc.strerror or exc}", severity="error")
            return
        self.directory = path
        self.marked.clear()
        self.name_filter = ""
        self.refresh_listing(select=old if old.parent == path else None)

    def action_parent(self) -> None:
        if self.focused is not None and isinstance(self.focused, Input):
            return
        self.change_directory(self.directory.parent)

    def action_close(self) -> None:
        if self.has_class("-look"):
            self.action_look()
            return
        search_row = self.query_one("#fm-search-row")
        if search_row.has_class("-visible"):
            search_row.remove_class("-visible")
            self.name_filter = ""
            self.refresh_listing()
            self.query_one(FileTable).focus()
            return
        self.dismiss(None)

    def action_toggle_focus(self) -> None:
        if self.mode == "save" and self.focused is self.query_one(FileTable):
            self.query_one("#fm-name", Input).focus()
        elif isinstance(self.focused, Input) or self.focused is self.query_one("#fm-preview-scroll"):
            self.query_one(FileTable).focus()
        else:
            self.query_one("#fm-preview-scroll").focus()

    def on_key(self, event: events.Key) -> None:
        if isinstance(self.focused, Input):
            return
        handlers = {
            "1": self.action_open,
            "o": self.action_open,
            "2": self.action_delete,
            "delete": self.action_delete,
            "3": self.action_move,
            "r": self.action_move,
            "f2": self.action_move,
            "4": self.action_copy,
            "c": self.action_copy,
            "5": self.action_mkdir,
            "m": self.action_mkdir,
            "6": self.action_look,
            "l": self.action_look,
            "7": self.action_other_directory,
            "g": self.action_other_directory,
            "n": self.action_name_search,
            "slash": self.action_name_search,
            "asterisk": self.action_mark,
            "space": self.action_mark,
            "h": self.action_home,
            "full_stop": self.action_hidden,
            "t": self.action_type_filter,
            "s": self.action_sort,
            "v": self.action_toggle_render,
        }
        handler = handlers.get(event.key)
        if handler is None:
            return
        if self.mode == "save" and event.key in ("1", "o", "2", "delete", "3", "r", "f2", "4", "c", "asterisk", "space"):
            return
        event.stop()
        event.prevent_default()
        handler()

    def action_open(self) -> None:
        if self.mode != "open":
            return
        files = self.selected_files()
        if files:
            self.dismiss(files)
        else:
            self.activate()

    def action_mark(self) -> None:
        entry = self.current_entry()
        if entry is None or entry.is_dir:
            return
        self.marked.symmetric_difference_update({entry.path})
        table = self.query_one(FileTable)
        row = table.cursor_row
        table.update_cell_at((row, 0), "*" if entry.path in self.marked else " ")
        if row + 1 < len(self.entries):
            table.move_cursor(row=row + 1)
        self._update_header()

    def action_home(self) -> None:
        self.change_directory(Path.home())

    def action_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        self.refresh_listing()

    def action_type_filter(self) -> None:
        self.documents_only = not self.documents_only
        self.refresh_listing()

    def action_sort(self) -> None:
        self.sort = SORTS[(SORTS.index(self.sort) + 1) % len(SORTS)]
        self.refresh_listing()

    def action_toggle_render(self) -> None:
        self.rendered_preview = not self.rendered_preview
        self.update_preview()

    def action_look(self) -> None:
        """Toggle a full-width preview, as WordPerfect's Look did."""
        self.toggle_class("-look")
        looking = self.has_class("-look")
        pane = self.query_one("#fm-preview-pane")
        if looking:
            pane.remove_class("-hidden")
            self.query_one("#fm-preview-scroll").focus()
        else:
            pane.set_class(self.size.width < 90, "-hidden")
            self.query_one(FileTable).focus()

    def action_name_search(self) -> None:
        row = self.query_one("#fm-search-row")
        row.add_class("-visible")
        search = self.query_one("#fm-search", Input)
        search.value = self.name_filter
        search.focus()

    @on(Input.Changed, "#fm-search")
    def _search_changed(self, event: Input.Changed) -> None:
        self.name_filter = event.value
        self.refresh_listing()

    @on(Input.Submitted, "#fm-search")
    def _search_done(self, event: Input.Submitted) -> None:
        self.query_one(FileTable).focus()

    @on(Input.Submitted, "#fm-name")
    def _name_submitted(self, event: Input.Submitted) -> None:
        self.save_here()

    @work
    async def save_here(self) -> None:
        name = self.query_one("#fm-name", Input).value.strip()
        if not name:
            self.notify("Type a file name first.", severity="warning")
            return
        target = Path(name).expanduser()
        if not target.is_absolute():
            target = self.directory / target
        if target.is_dir():
            self.change_directory(target)
            self.query_one("#fm-name", Input).value = ""
            return
        if not target.suffix:
            target = target.with_suffix(self.inkmill.default_extension())
        if target.exists():
            answer = await self.app.push_screen_wait(
                ConfirmDialog("Replace?", f"{target.name} already exists. Replace it?")
            )
            if answer != "yes":
                return
        self.dismiss(target)

    @work
    async def action_delete(self) -> None:
        if self.mode != "open":
            return
        targets = self.selected_files()
        entry = self.current_entry()
        if not targets and entry and entry.is_dir and not entry.label:
            targets = [entry.path]
        if not targets:
            return
        what = targets[0].name if len(targets) == 1 else f"{len(targets)} marked files"
        answer = await self.app.push_screen_wait(ConfirmDialog("Delete", f"Delete {what}?"))
        if answer != "yes":
            return
        for path in targets:
            try:
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
                self.inkmill.file_deleted(path)
            except OSError as exc:
                reason = "folder is not empty" if path.is_dir() else (exc.strerror or str(exc))
                self.notify(f"Cannot delete {path.name}: {reason}", severity="error")
        self.marked.clear()
        self.refresh_listing()

    @work
    async def action_move(self) -> None:
        if self.mode != "open":
            return
        entry = self.current_entry()
        targets = self.selected_files() or ([entry.path] if entry and not entry.label else [])
        if not targets:
            return
        if len(targets) == 1:
            prompt, default = "New name or path:", str(targets[0])
        else:
            prompt, default = f"Move {len(targets)} files to folder:", str(self.directory)
        answer = await self.app.push_screen_wait(InputDialog("Move/Rename", prompt, default))
        if not answer:
            return
        dest = Path(answer).expanduser()
        if not dest.is_absolute():
            dest = self.directory / dest
        if len(targets) > 1 and not dest.is_dir():
            self.notify(f"{dest} is not a folder.", severity="error")
            return
        for path in targets:
            target = dest / path.name if dest.is_dir() else dest
            if target.exists() and target != path:
                self.notify(f"{target} already exists; skipped.", severity="warning")
                continue
            try:
                shutil.move(str(path), str(target))
                self.inkmill.file_moved(path, target)
            except OSError as exc:
                self.notify(f"Cannot move {path.name}: {exc.strerror or exc}", severity="error")
        self.marked.clear()
        self.refresh_listing()

    @work
    async def action_copy(self) -> None:
        if self.mode != "open":
            return
        targets = self.selected_files()
        if not targets:
            return
        default = str(self.directory / f"Copy of {targets[0].name}") if len(targets) == 1 else str(self.directory)
        answer = await self.app.push_screen_wait(InputDialog("Copy", "Copy to:", default))
        if not answer:
            return
        dest = Path(answer).expanduser()
        if not dest.is_absolute():
            dest = self.directory / dest
        for path in targets:
            target = dest / path.name if dest.is_dir() else dest
            if target.exists():
                self.notify(f"{target} already exists; skipped.", severity="warning")
                continue
            try:
                shutil.copy2(path, target)
            except OSError as exc:
                self.notify(f"Cannot copy {path.name}: {exc.strerror or exc}", severity="error")
        self.refresh_listing()

    @work
    async def action_mkdir(self) -> None:
        answer = await self.app.push_screen_wait(InputDialog("New Folder", "Folder name:"))
        if not answer:
            return
        path = Path(answer).expanduser()
        if not path.is_absolute():
            path = self.directory / path
        try:
            path.mkdir(parents=True)
        except OSError as exc:
            self.notify(f"Cannot create folder: {exc.strerror or exc}", severity="error")
            return
        self.refresh_listing(select=path)

    @work
    async def action_other_directory(self) -> None:
        answer = await self.app.push_screen_wait(InputDialog("Other Directory", "Directory:", str(self.directory)))
        if answer:
            self.change_directory(Path(answer))
