"""Top menu bar and pull-down menus.

The bar is hidden while writing (``menu_bar = "auto"``) and appears when the
menu key is pressed (Esc, F10 or Alt+=). Navigation follows the DOS/Windows
convention: Left/Right move between menus, Up/Down move within one, Enter or
the highlighted letter runs an item, Esc backs out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.geometry import Offset
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..commands import format_key
from ..menus import Menu, MenuItem, Separator, split_accelerator

if TYPE_CHECKING:
    from ..app import InkmillApp


class MenuStrip(Widget):
    """One line listing the menu titles, with accelerator letters marked."""

    COMPONENT_CLASSES = {"menustrip--key", "menustrip--selected", "menustrip--hint"}

    DEFAULT_CSS = """
    MenuStrip {
        height: 1;
        width: 100%;
        background: $im-menu-bg;
        color: $im-menu-fg;
    }
    MenuStrip > .menustrip--key { color: $im-menu-key; text-style: bold; }
    MenuStrip > .menustrip--selected { background: $im-menu-hl-bg; color: $im-menu-hl-fg; }
    MenuStrip > .menustrip--hint { color: $im-menu-fg; text-style: dim; }
    """

    class Picked(Message):
        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    def __init__(self, menus: list[Menu], selected: int | None = None, hint: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.menus = menus
        self.selected = selected
        self.hint = hint
        self._spans: list[tuple[int, int]] = []

    def select(self, index: int | None) -> None:
        self.selected = index
        self.refresh()

    def menu_x(self, index: int) -> int:
        self.render()
        return self._spans[index][0] if index < len(self._spans) else 0

    def render(self) -> Text:
        key_style = self.get_component_rich_style("menustrip--key", partial=True)
        sel_style = self.get_component_rich_style("menustrip--selected", partial=True)
        text = Text(" ")
        self._spans = []
        for i, menu in enumerate(self.menus):
            plain, _accel, idx = split_accelerator(menu.label)
            start = len(text)
            item = Text(f" {plain} ")
            if idx >= 0:
                item.stylize(key_style, idx + 1, idx + 2)
            if i == self.selected:
                item.stylize(sel_style)
            text.append_text(item)
            self._spans.append((start, len(text)))
            text.append(" ")
        if self.hint:
            hint_style = self.get_component_rich_style("menustrip--hint", partial=True)
            pad = max(1, self.size.width - len(text) - len(self.hint) - 1)
            text.append(" " * pad)
            text.append(self.hint, style=hint_style)
        return text

    def on_click(self, event: events.Click) -> None:
        for i, (start, end) in enumerate(self._spans):
            if start <= event.x < end:
                event.stop()
                self.post_message(self.Picked(i))
                return


class MenuDropdown(OptionList):
    DEFAULT_CSS = """
    MenuDropdown {
        width: auto;
        height: auto;
        max-height: 80vh;
        min-width: 16;
        background: $im-menu-bg;
        color: $im-menu-fg;
        border: round $im-menu-fg;
        padding: 0;
        scrollbar-size-vertical: 1;
    }
    MenuDropdown:focus { border: round $im-menu-fg; background-tint: transparent; }
    MenuDropdown > .option-list--option-highlighted,
    MenuDropdown:focus > .option-list--option-highlighted {
        background: $im-menu-hl-bg;
        color: $im-menu-hl-fg;
        text-style: none;
    }
    MenuDropdown > .option-list--option-disabled { color: $im-menu-fg 50%; }
    MenuDropdown > .option-list--separator { color: $im-menu-fg 60%; }
    """


class MenuScreen(ModalScreen[str | None]):
    """Shows the bar plus one open pull-down; dismisses with a command id."""

    DEFAULT_CSS = """
    MenuScreen {
        background: transparent;
        align: left top;
    }
    MenuScreen > MenuStrip { dock: top; }
    MenuScreen > MenuDropdown { margin: 0; }
    """

    BINDINGS = [
        Binding("left", "move(-1)", show=False),
        Binding("right", "move(1)", show=False),
        Binding("escape,f10,alt+equals_sign", "close", show=False),
    ]

    def __init__(self, start: int = 0) -> None:
        super().__init__()
        self.index = start
        self._items: list[MenuItem] = []

    @property
    def inkmill(self) -> "InkmillApp":
        return self.app  # type: ignore[return-value]

    @property
    def menus(self) -> list[Menu]:
        return list(self.inkmill.menus)

    def compose(self) -> ComposeResult:
        yield MenuStrip(self.menus, self.index, hint=self.inkmill.menu_hint())
        yield MenuDropdown()

    def on_mount(self) -> None:
        self._show(self.index)

    def _show(self, index: int) -> None:
        menus = self.menus
        if not menus:
            self.dismiss(None)
            return
        self.index = index % len(menus)
        strip = self.query_one(MenuStrip)
        strip.select(self.index)
        dropdown = self.query_one(MenuDropdown)
        dropdown.clear_options()
        self._items = []
        menu = menus[self.index]
        rows = []
        for entry in menu.items:
            if isinstance(entry, Separator):
                rows.append(None)
                continue
            command = self.inkmill.commands.get(entry.command)
            if command is None:
                continue
            rows.append((entry, command))
        label_w = max((len(split_accelerator(e.label or c.label)[0]) for r in rows if r for e, c in [r]), default=4)
        key_w = max((len(format_key(c.keys[0])) for r in rows if r for _e, c in [r] if c.keys), default=0)
        options: list[Option | None] = []
        for row in rows:
            if row is None:
                if options and options[-1] is not None:
                    options.append(None)
                continue
            entry, command = row
            options.append(self._option(entry, command, label_w, key_w))
            self._items.append(entry)
        while options and options[-1] is None:
            options.pop()
        dropdown.add_options(options)
        x = strip.menu_x(self.index)
        dropdown.styles.offset = Offset(max(0, x), 0)
        dropdown.focus()
        first = next((i for i, opt in enumerate(dropdown._options) if not opt.disabled), None)
        dropdown.highlighted = first

    def _option(self, entry: MenuItem, command, label_w: int, key_w: int) -> Option:
        plain, _accel, idx = split_accelerator(entry.label or command.label)
        text = Text(" ")
        label = Text(plain.ljust(label_w))
        if idx >= 0:
            label.stylize("underline", idx, idx + 1)
        text.append_text(label)
        if key_w:
            key = format_key(command.keys[0]) if command.keys else ""
            text.append("  " + key.rjust(key_w))
        text.append(" ")
        return Option(text, id=command.id, disabled=not command.is_enabled(self.inkmill))

    def action_move(self, step: int) -> None:
        self._show(self.index + step)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_menu_strip_picked(self, message: MenuStrip.Picked) -> None:
        self._show(message.index)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def on_key(self, event: events.Key) -> None:
        key = event.key
        if key.startswith("alt+") and len(key) == 5:
            letter = key[-1].lower()
            for i, menu in enumerate(self.menus):
                if menu.accelerator == letter:
                    event.stop()
                    self._show(i)
                    return
        if event.character and len(event.character) == 1 and event.character.isalnum():
            letter = event.character.lower()
            for entry in self._items:
                command = self.inkmill.commands.get(entry.command)
                if command is None:
                    continue
                if split_accelerator(entry.label or command.label)[1] == letter:
                    event.stop()
                    if command.is_enabled(self.inkmill):
                        self.dismiss(command.id)
                    return

    def on_click(self, event: events.Click) -> None:
        # A click outside the strip and the dropdown closes the menu.
        widget, _ = self.get_widget_at(event.screen_x, event.screen_y)
        if widget is self:
            self.dismiss(None)
