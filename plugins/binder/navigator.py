"""The Binder navigator (Alt+F5).

Shows the binder this document belongs to with its contents in order, the
previous and next documents, related documents and documents that link here.
Enter opens the highlighted one. ``[`` and ``]`` move a chapter up or down in
the binder's contents.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from inkmill.screens.dialogs import Dialog

from . import model


class NavigatorScreen(Dialog):
    """Dismisses with the path (as a string) to open, or None."""

    DEFAULT_CSS = Dialog.DEFAULT_CSS + """
    NavigatorScreen .im-dialog { width: 76; }
    NavigatorScreen OptionList { max-height: 24; }
    NavigatorScreen #bn-hint { color: $im-dialog-fg 70%; margin-top: 1; }
    """

    def __init__(self, path: Path, read, write) -> None:
        super().__init__()
        self.path = model.norm(path)
        self.read = read
        self.write = write
        self.binder: Path | None = None
        self.focus_after: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label("Binder", classes="im-title")
            yield OptionList(id="bn-list")
            yield Label("Enter open   [ ] move chapter   Esc close", id="bn-hint")

    def on_mount(self) -> None:
        self.rebuild()
        self.query_one(OptionList).focus()

    def _title(self, path: Path) -> str:
        return model.title_of(path, self.read(path))

    def _row(self, path: Path, label: str, *, here: bool = False, number: int | None = None, indent: int = 2) -> Option:
        text = Text(" " * indent)
        if number is not None:
            text.append(f"{number:>3}  ")
        title = label or self._title(path)
        text.append(title, style="bold" if here else "")
        if here:
            text.append("  (this document)")
        elif not path.exists():
            text.append("  (missing)", style="italic")
        text.append(f"   {model.relref(self.path, path)}", style="dim")
        return Option(text, id=f"{'here' if here else 'go'}|{path}")

    @staticmethod
    def _heading(label: str) -> Option:
        return Option(Text(label, style="bold underline"), disabled=True)

    def rebuild(self) -> None:
        options: list[Option] = []
        links = model.read_links(self.path, self.read(self.path))
        pos = model.position(links, self.read)
        self.binder = None
        if links.is_binder:
            self.binder = self.path
            options.append(self._heading(f"{links.title} (this binder)"))
            for i, item in enumerate(links.contents, start=1):
                options.append(self._row(item, "", number=i))
        elif pos.binder is not None:
            self.binder = pos.binder
            options.append(self._heading("Binder"))
            options.append(self._row(pos.binder, ""))
            contents = pos.binder_links.contents if pos.binder_links else []
            if contents:
                options.append(self._heading("Contents"))
                for i, item in enumerate(contents, start=1):
                    options.append(self._row(item, "", here=model.same(item, self.path), number=i))
        others = [p for p in links.parents if pos.binder is None or not model.same(p, pos.binder)]
        if others:
            options.append(self._heading("Also in"))
            options += [self._row(p, "") for p in others]
        in_contents = pos.index >= 0 or links.is_binder
        if pos.previous and (links.previous or not in_contents):
            options.append(self._heading("Previous"))
            options.append(self._row(pos.previous, ""))
        if pos.next and (links.next or not in_contents):
            options.append(self._heading("Next"))
            options.append(self._row(pos.next, ""))
        if links.related:
            options.append(self._heading("Related"))
            options += [self._row(p, "") for p in links.related]
        known = {str(p) for _, p in links.all()} | ({str(pos.binder)} if pos.binder else set())
        if pos.binder_links:
            known |= {str(p) for p in pos.binder_links.contents}
        incoming = [(rel, p) for rel, p in model.backlinks(self.path, self.read) if str(p) not in known]
        if incoming:
            options.append(self._heading("Linked from"))
            seen = set()
            for _rel, p in incoming:
                if str(p) not in seen:
                    seen.add(str(p))
                    options.append(self._row(p, ""))
        if not options:
            options.append(Option(Text("No linked documents yet. Document > Link Document... adds one."), disabled=True))
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        option_list.add_options(options)
        target = self.focus_after or f"here|{self.path}"
        for i, option in enumerate(options):
            if option.id == target or (option.id and option.id.endswith(f"|{self.path}") and target.startswith("here")):
                option_list.highlighted = i
                break
        else:
            for i, option in enumerate(options):
                if not option.disabled:
                    option_list.highlighted = i
                    break
        self.focus_after = None

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id and event.option.id.startswith("go|"):
            self.dismiss(event.option.id.removeprefix("go|"))

    def on_key(self, event: events.Key) -> None:
        if event.character not in ("[", "]"):
            return
        event.stop()
        if self.binder is None:
            self.notify("This document is not in a binder.")
            return
        option_list = self.query_one(OptionList)
        option = option_list.highlighted_option if option_list.highlighted is not None else None
        if option is None or not option.id:
            return
        target = Path(option.id.split("|", 1)[1])
        if option.id.startswith("here|"):
            target = self.path
        text = self.read(self.binder) or ""
        updated = model.move_in_contents(text, self.binder, target, -1 if event.character == "[" else 1)
        if updated != text:
            self.write(self.binder, updated)
            self.focus_after = option.id
            self.rebuild()
