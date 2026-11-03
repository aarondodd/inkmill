"""The side panel: a column at the right that plugins fill on demand.

It stays hidden until a plugin shows something in it (an outline, findings,
an AI reply), so the writing screen stays empty by default. On narrow
terminals it covers the editor instead of squeezing it.

Ctrl+T moves the focus between the editor and the panel; Esc in the panel
closes it.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Label

NARROW = 90


class SidePanel(Vertical):
    DEFAULT_CSS = """
    SidePanel {
        width: 46;
        height: 1fr;
        display: none;
        background: $im-dialog-bg;
        color: $im-dialog-fg;
        border-left: tall $im-dialog-border;
        padding: 0 1;
    }
    SidePanel.-visible { display: block; }
    SidePanel.-narrow { width: 100%; border-left: none; }
    SidePanel > #panel-title { width: 100%; text-style: bold; content-align: center middle; height: 1; }
    SidePanel > #panel-body { height: 1fr; }
    SidePanel > #panel-hint { width: 100%; height: auto; color: $im-dialog-fg 70%; }
    SidePanel #panel-body > * { height: 1fr; }
    SidePanel #panel-hint { height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    SidePanel OptionList, SidePanel VerticalScroll {
        background: $im-input-bg;
        color: $im-input-fg;
        border: none;
        scrollbar-size-vertical: 1;
    }
    SidePanel OptionList > .option-list--option-highlighted,
    SidePanel OptionList:focus > .option-list--option-highlighted {
        background: $im-select-bg;
        color: $im-select-fg;
        text-style: none;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.owner: str | None = None
        self.content: Widget | None = None

    def compose(self) -> ComposeResult:
        yield Label("", id="panel-title")
        yield Vertical(id="panel-body")
        yield Label("", id="panel-hint")

    @property
    def visible(self) -> bool:
        return self.has_class("-visible")

    async def show(self, widget: Widget, title: str, owner: str, hint: str = "", *, focus: bool = True) -> None:
        body = self.query_one("#panel-body", Vertical)
        await body.remove_children()
        self.content = widget
        self.owner = owner
        await body.mount(widget)
        self.query_one("#panel-title", Label).update(title)
        self.query_one("#panel-hint", Label).update(hint or "Ctrl+T editor   Esc close")
        self.add_class("-visible")
        self.set_narrow(self.app.size.width < NARROW)
        if focus:
            self.focus_content()

    def set_title(self, title: str) -> None:
        self.query_one("#panel-title", Label).update(title)

    def set_hint(self, hint: str) -> None:
        self.query_one("#panel-hint", Label).update(hint)

    def set_narrow(self, narrow: bool) -> None:
        self.set_class(narrow, "-narrow")
        self._update_page()

    def _update_page(self) -> None:
        # On a narrow screen the open panel takes the whole width.
        if self.parent is not None:
            self.parent.set_class(self.visible and self.has_class("-narrow"), "-panel-full")

    def focus_content(self) -> None:
        if self.content is None:
            return
        target = self.content if self.content.can_focus else next(
            (w for w in self.content.query("*") if w.can_focus), None
        )
        if target is not None:
            target.focus()

    def hide(self) -> None:
        self.remove_class("-visible")
        self.owner = None
        self._update_page()

    def contains_focus(self) -> bool:
        focused = self.app.focused
        while focused is not None:
            if focused is self:
                return True
            focused = focused.parent  # type: ignore[assignment]
        return False
