"""Links: [[wikilinks]] between notes, and following any link.

* Follow Link (Alt+L) opens what is under the cursor: a [[wikilink]] (by
  file name or title, anywhere in the project), a Markdown link to a file or
  a heading, or a web address. A wikilink to a note that does not exist yet
  offers to create it. Link Back (Alt+Left) returns to where you were.
* Insert Link to Note... picks a note by typing part of its name.
* Backlinks lists the notes that link to this one, in the side panel.

``[[Note]]``, ``[[Note|shown text]]`` and ``[[Note#Heading]]`` all work, and
wikilinks become links in the HTML export.
"""

from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from inkmill.screens.dialogs import ConfirmDialog, Dialog

from . import model

STALE = 30.0  # seconds before the note index is rebuilt


class NotePicker(Dialog):
    """Type to filter; Enter picks. Dismisses with a Path or None."""

    DEFAULT_CSS = Dialog.DEFAULT_CSS + """
    NotePicker .im-dialog { width: 70; }
    NotePicker OptionList { max-height: 16; }
    """

    def __init__(self, title: str, root: Path, files: list[Path]) -> None:
        super().__init__()
        self.title_text = title
        self.root = root
        self.files = sorted(files, key=lambda p: str(p).lower())
        self.shown: list[Path] = []

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label(self.title_text, classes="im-title")
            yield Input(placeholder="Type part of a name", id="np-filter")
            yield OptionList(id="np-list")

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self.refilter("")

    def refilter(self, needle: str) -> None:
        needle = needle.lower()
        self.shown = [p for p in self.files if needle in p.stem.lower() or needle in str(p.relative_to(self.root)).lower()][:200]
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for i, path in enumerate(self.shown):
            line = Text(path.stem, style="bold")
            line.append(f"  {path.relative_to(self.root).parent.as_posix()}", style="dim")
            option_list.add_option(Option(line, id=str(i)))
        if self.shown:
            option_list.highlighted = 0

    @on(Input.Changed)
    def changed(self, event: Input.Changed) -> None:
        self.refilter(event.value)

    @on(Input.Submitted)
    def submitted(self, _event: Input.Submitted) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is not None and self.shown:
            self.dismiss(self.shown[option_list.highlighted])

    def on_key(self, event) -> None:
        if event.key in ("down", "up") and isinstance(self.focused, Input):
            option_list = self.query_one(OptionList)
            if self.shown:
                current = option_list.highlighted or 0
                step = 1 if event.key == "down" else -1
                option_list.highlighted = max(0, min(len(self.shown) - 1, current + step))
            event.stop()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.shown[int(event.option.id)])


class BacklinkList(OptionList):
    def __init__(self, open_at) -> None:
        super().__init__()
        self.open_at = open_at
        self.targets: list[tuple[Path, int]] = []

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id:
            self.open_at(*self.targets[int(event.option.id)])


def register(api):
    app = api.app
    indexes: dict[str, model.Index] = {}
    history: list[tuple[Path | None, int, tuple[int, int]]] = []

    def doc_path() -> Path | None:
        doc = app.active_document
        return doc.path.resolve() if doc is not None and doc.path is not None else None

    def has_path(_app) -> bool:
        return doc_path() is not None

    async def index_for(path: Path, *, fresh: bool = False) -> model.Index:
        root = model.project_root(path)
        key = str(root)
        idx = indexes.get(key)
        if fresh or idx is None or time.monotonic() - idx.built > STALE:
            idx = await api.run_in_thread(model.Index(root).build)
            indexes[key] = idx
        return idx

    def remember() -> None:
        doc = app.active_document
        editor = app.active_editor
        if doc is not None and editor is not None:
            history.append((doc.path, doc.id, editor.cursor_location))
            del history[:-50]

    async def open_at(path: Path, line: int | None = None) -> None:
        await app.open_path(path)
        editor = app.active_editor
        if editor is not None and line is not None:
            editor.cursor_location = (min(line, editor.document.line_count - 1), 0)
            editor.scroll_cursor_visible(center=True)
            editor.focus()

    def jump_to_anchor(anchor: str) -> bool:
        editor = app.active_editor
        line = model.heading_line(editor.text, anchor) if editor else None
        if line is None:
            app.status.flash(f"No heading {anchor!r} here.")
            return False
        editor.cursor_location = (line, 0)
        editor.scroll_cursor_visible(center=True)
        return True

    # -- following --------------------------------------------------------------

    @api.command("links.follow", "Follow &Link", "alt+l", menu="document", separator=True,
                 enabled=lambda a: a.active_editor is not None,
                 description="Open the wikilink, file, heading or web address under the cursor")
    async def follow(app):
        editor = app.active_editor
        row, col = editor.cursor_location
        link = model.link_at(editor.document.get_line(row), col)
        if link is None:
            app.status.flash("No link under the cursor.")
            return
        here = doc_path()
        if link.kind == "url":
            from inkmill.system import open_url

            try:
                how = open_url(link.target)
                app.status.flash(f"Opened {link.target} ({how}).")
            except RuntimeError as exc:
                app.notify(str(exc), severity="warning")
            return
        if link.kind == "anchor":
            remember()
            jump_to_anchor(link.anchor)
            return
        if here is None:
            app.status.flash("Save the document first, so links have a folder to start from.")
            return
        if link.kind == "file":
            target = (here.parent / urllib.parse.unquote(link.target)).resolve()
            if not target.exists():
                app.notify(f"{link.target} does not exist.", severity="warning")
                return
            if target.suffix.lower() not in model.DOC_SUFFIXES:
                from inkmill.system import open_file

                open_file(target)
                return
        else:
            idx = await index_for(here)
            target = idx.find(link.target, here)
            if target is None:
                idx = await index_for(here, fresh=True)
                target = idx.find(link.target, here)
            if target is None:
                name = link.target.replace("/", "-")
                answer = await app.push_screen_wait(ConfirmDialog(
                    "New note", f"No note called {link.target!r} yet. Create {name}.md next to this document?"
                ))
                if answer != "yes":
                    return
                target = here.parent / f"{name}.md"
                target.write_text(f"# {link.target}\n\n", encoding="utf-8")
                indexes.clear()
        remember()
        await open_at(target)
        if link.anchor:
            jump_to_anchor(link.anchor)

    @api.command("links.back", "Link &Back", "alt+left", menu="document",
                 description="Return to where you followed the last link from")
    async def back(app):
        while history:
            path, doc_id, cursor = history.pop()
            doc = app.docs.find_path(path) if path else next((d for d in app.docs if d.id == doc_id), None)
            if doc is None and path is not None and path.exists():
                doc = await app.open_path(path)
            if doc is None:
                continue
            app.activate(doc)
            editor = app.active_editor
            if editor is not None:
                editor.cursor_location = cursor
                editor.scroll_cursor_visible(center=True)
            return
        app.status.flash("Nowhere to go back to.")

    # -- inserting -------------------------------------------------------------

    @api.command("links.insert", "Insert Link to No&te...", menu="document", enabled=has_path,
                 description="Pick a note and insert a [[wikilink]] to it")
    async def insert(app):
        here = doc_path()
        idx = await index_for(here, fresh=True)
        files = [p for p in idx.files if p.resolve() != here]
        if not files:
            app.status.flash(f"No other notes under {idx.root}.")
            return
        picked = await app.push_screen_wait(NotePicker(f"Link to a note in {idx.root.name}", idx.root, files))
        if picked is None:
            return
        name = picked.stem
        if len(idx.by_name.get(name.lower(), [])) > 1:
            name = picked.relative_to(idx.root).with_suffix("").as_posix()
        editor = app.active_editor
        selected = editor.selected_text
        text = f"[[{name}|{selected}]]" if selected else f"[[{name}]]"
        editor.replace(text, *sorted([editor.selection.start, editor.selection.end]))
        editor.focus()

    # -- backlinks --------------------------------------------------------------

    @api.command("links.backlinks", "Bac&klinks", menu="document", enabled=has_path,
                 description="Notes that link to this one, in the side panel")
    async def backlinks(app):
        here = doc_path()
        idx = await index_for(here, fresh=True)
        names = {here.stem.lower()}
        doc = app.active_document
        title = model.frontmatter.read(doc.text).get("title")
        if isinstance(title, str) and title.strip():
            names.add(title.strip().lower())

        def scan() -> list[tuple[Path, int, str]]:
            found = []
            for path in idx.files:
                if path.resolve() == here:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                lines = text.split("\n")
                for line in model.references(text, here, names):
                    found.append((path, line, lines[line].strip()))
            return found

        found = await api.run_in_thread(scan)
        widget = BacklinkList(open_at)
        for i, (path, line, snippet) in enumerate(found):
            widget.targets.append((path, line))
            entry = Text(path.stem, style="bold")
            entry.append(f"  {line + 1}\n", style="dim")
            entry.append(snippet[:80])
            widget.add_option(Option(entry, id=str(i)))
        if not found:
            widget.add_option(Option(f"Nothing under {idx.root.name} links here yet.", disabled=True))
        await api.show_panel(widget, f"Backlinks: {len(found)}", "Enter open  Ctrl+T text  Esc close")

    # -- export -------------------------------------------------------------------

    def extend(md) -> None:
        def wikilink(state, silent):
            src, pos = state.src, state.pos
            if not src.startswith("[[", pos):
                return False
            end = src.find("]]", pos + 2)
            if end == -1:
                return False
            inner = src[pos + 2:end]
            if not inner.strip() or "\n" in inner or "[" in inner:
                return False
            if not silent:
                link = model.parse_wikilink(inner)
                href = urllib.parse.quote(link.target) + ".html" if link.target else ""
                if link.anchor:
                    href += "#" + model.slug(link.anchor)
                token = state.push("link_open", "a", 1)
                token.attrSet("href", href)
                token.attrSet("class", "wikilink")
                text = state.push("text", "", 0)
                text.content = link.label or (link.target + (f" > {link.anchor}" if link.anchor and link.target else link.anchor))
                state.push("link_close", "a", -1)
            state.pos = end + 2
            return True

        md.inline.ruler.before("link", "wikilink", wikilink)

    api.markdown_extension(extend)

    class Service:
        """For other plugins: wikilinks turned into their visible text."""

        @staticmethod
        def plain(text: str) -> str:
            def label(m):
                link = model.parse_wikilink(m.group(1))
                return link.label or link.target or link.anchor
            return model.WIKILINK.sub(label, text)

        @staticmethod
        def find(name: str, near: Path) -> Path | None:
            return model.Index(model.project_root(near)).build().find(name, near)

    api.provide("links", Service())
