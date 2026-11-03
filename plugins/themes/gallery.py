"""The theme gallery: pick a theme while seeing it applied.

Moving the highlight switches the whole screen to that theme, so the editor
behind the list is the preview. Enter keeps it, Esc puts the old one back.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from inkmill.screens.dialogs import Dialog

GROUPS = (
    ("inkmill", "Inkmill"),
    ("bundled", "Themes plugin"),
    ("yours", "Your themes"),
    ("textual", "Textual"),
)


class GalleryScreen(Dialog):
    """Dismisses with ``(action, theme name)``: ("apply" | "new", name), or None."""

    DEFAULT_CSS = Dialog.DEFAULT_CSS + """
    GalleryScreen { align: right middle; background: transparent; }
    GalleryScreen .im-dialog { width: 46; min-width: 40; margin-right: 2; height: 90%; max-height: 32; }
    GalleryScreen .im-dialog OptionList { height: 1fr; max-height: 100%; }
    GalleryScreen #tg-about { width: 100%; height: 3; margin-top: 1; }
    GalleryScreen #tg-hint { color: $im-dialog-fg 70%; }
    """

    BINDINGS = Dialog.BINDINGS + [Binding("n", "new", show=False)]

    def __init__(self, infos: dict, current: str) -> None:
        super().__init__()
        self.infos = infos
        self.original = current

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label("Theme Gallery", classes="im-title")
            yield OptionList(id="tg-list")
            yield Label("", id="tg-about")
            yield Label("Enter keep   N new from this   Esc cancel", id="tg-hint")

    def on_mount(self) -> None:
        options: list[Option] = []
        for group, title in GROUPS:
            members = sorted((i for i in self.infos.values() if i.source == group), key=lambda i: i.label.lower())
            if not members:
                continue
            options.append(Option(Text(title, style="bold underline"), disabled=True))
            for info in members:
                options.append(Option(Text("  " + info.label), id=info.theme.name))
        option_list = self.query_one(OptionList)
        option_list.add_options(options)
        for i, option in enumerate(options):
            if option.id == self.original:
                option_list.highlighted = i
                break
        option_list.focus()
        self._describe(self.original)

    def _describe(self, name: str | None) -> None:
        info = self.infos.get(name) if name else None
        about = self.query_one("#tg-about", Label)
        if info is None:
            about.update("")
            return
        text = info.inspired_by or {"textual": "A theme that ships with Textual.", "inkmill": "Built into Inkmill."}.get(info.source, "")
        if info.path is not None and info.source == "yours":
            text = f"{text}\n{info.path.name}" if text else info.path.name
        about.update(text)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        name = event.option.id
        if name and name in self.app.available_themes:
            self.app.theme = name
        self._describe(name)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(("apply", event.option.id))

    def action_new(self) -> None:
        option = self.query_one(OptionList).highlighted_option
        if option is not None and option.id:
            self.app.theme = self.original
            self.dismiss(("new", option.id))

    def action_cancel(self) -> None:
        self.app.theme = self.original
        self.dismiss(None)
