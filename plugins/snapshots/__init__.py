"""Snapshots: named versions of a document, without git.

Take Snapshot (Ctrl+F5) saves the document as it is now, with an optional
name. Snapshots... lists them: Enter compares one with the current text, R
restores it (after snapshotting the current text first), O opens it as a new
document, N renames and D deletes. Snapshots can also be taken automatically
when you save.
"""

from __future__ import annotations

import time

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from inkmill.config import state_dir
from inkmill.screens.dialogs import ConfirmDialog, Dialog, InputDialog, TextDialog

from .store import Store, compare


class SnapshotList(Dialog):
    """Dismisses with (action, Snapshot) or None."""

    DEFAULT_CSS = Dialog.DEFAULT_CSS + """
    SnapshotList .im-dialog { width: 74; }
    SnapshotList OptionList { max-height: 18; }
    SnapshotList #sn-hint { color: $im-dialog-fg 70%; margin-top: 1; }
    """

    def __init__(self, title: str, snapshots, current_words: int) -> None:
        super().__init__()
        self.title_text = title
        self.snapshots = snapshots
        self.current_words = current_words

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label(self.title_text, classes="im-title")
            options = []
            for i, snap in enumerate(self.snapshots):
                delta = self.current_words - snap.words
                text = Text(f"{snap.when}  {snap.words:>7,} words ({delta:+,} since)  ")
                text.append(snap.name or "", style="bold")
                options.append(Option(text, id=str(i)))
            yield OptionList(*options)
            yield Label("Enter compare   R restore   O open copy   N rename   D delete   Esc close", id="sn-hint")

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def _current(self):
        option = self.query_one(OptionList).highlighted_option
        return self.snapshots[int(option.id)] if option is not None else None

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(("compare", self.snapshots[int(event.option.id)]))

    def on_key(self, event: events.Key) -> None:
        actions = {"r": "restore", "o": "open", "n": "rename", "d": "delete", "delete": "delete"}
        key = (event.character or "").lower() or event.key
        if key in actions and self._current() is not None:
            event.stop()
            self.dismiss((actions[key], self._current()))


def register(api):
    app = api.app
    last_auto: dict[str, float] = {}

    def store_for(doc) -> Store:
        return Store(doc.path, state_dir() / "snapshots", beside=api.settings.get("location") == "beside")

    def has_path(_app) -> bool:
        doc = app.active_document
        return doc is not None and doc.path is not None

    @api.command("snapshots.take", "Take Snaps&hot...", "ctrl+f5", menu="file", enabled=has_path,
                 description="Save a named copy of this document as it is now")
    async def take(app):
        doc = app.active_document
        name = await app.push_screen_wait(InputDialog("Take Snapshot", "Name (optional):", ""))
        if name is None:
            return
        snap = await api.run_in_thread(store_for(doc).take, doc.text, name.strip())
        app.status.flash(f"Snapshot taken: {snap.when}" + (f" ({snap.name})" if snap.name else ""))

    @api.command("snapshots.list", "&Browse Snapshots...", menu="file", enabled=has_path,
                 description="Compare with, restore or open earlier versions")
    async def browse(app):
        doc = app.active_document
        store = store_for(doc)
        while True:
            snaps = store.list()
            if not snaps:
                app.status.flash("No snapshots of this document yet. Ctrl+F5 takes one.")
                return
            result = await app.push_screen_wait(SnapshotList(f"Snapshots: {doc.title}", snaps, doc.word_count()))
            if result is None:
                return
            action, snap = result
            if action == "compare":
                body = await api.run_in_thread(compare, snap.read(), doc.text)
                header = Text(f"From the snapshot of {snap.when}" + (f" ({snap.name})" if snap.name else "")
                              + " to the text now. Struck out: removed. Underlined: added.\n", style="italic")
                await app.push_screen_wait(TextDialog("Compare", header + body))
            elif action == "restore":
                answer = await app.push_screen_wait(ConfirmDialog(
                    "Restore snapshot",
                    f"Replace the text with the snapshot of {snap.when}?\nThe current text is snapshotted first.",
                ))
                if answer == "yes":
                    store.take(doc.text, f"Before restoring {snap.when}")
                    app.replace_document_text(doc, snap.read())
                    app.status.flash(f"Restored {snap.when}. Save to keep it; Ctrl+Z undoes it.")
                    return
            elif action == "open":
                await app.new_document(snap.read(), doc.format)
                app.status.flash(f"Opened a copy of the snapshot of {snap.when}.")
                return
            elif action == "rename":
                name = await app.push_screen_wait(InputDialog("Rename Snapshot", "Name:", snap.name))
                if name is not None:
                    store.rename(snap, name.strip())
            elif action == "delete":
                answer = await app.push_screen_wait(ConfirmDialog("Delete snapshot", f"Delete the snapshot of {snap.when}?"))
                if answer == "yes":
                    store.delete(snap)

    @api.on("document_saved")
    def saved(app, doc):
        minutes = api.settings.get("on_save_every_minutes", 0)
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            return
        if minutes <= 0 or doc.path is None:
            return
        key = str(doc.path.resolve())
        if time.time() - last_auto.get(key, 0) < minutes * 60:
            return
        last_auto[key] = time.time()
        store_for(doc).take(doc.text, "Automatic, on save")
