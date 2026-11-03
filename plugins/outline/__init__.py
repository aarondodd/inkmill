"""Outline: the document's headings in the side panel.

F8 opens it. Enter jumps to a heading; ``[`` and ``]`` move the whole section
up or down among its siblings; ``<`` and ``>`` promote or demote it with its
subsections. The list follows your edits while it is open.
"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from . import model

HINT = "Enter go  [ ] move  < > level  Ctrl+T text  Esc close"


class OutlineList(OptionList):
    """The heading list; keys act on the highlighted section."""

    def __init__(self, plugin) -> None:
        super().__init__()
        self.plugin = plugin

    def on_key(self, event: events.Key) -> None:
        actions = {"[": ("move", -1), "]": ("move", 1), "<": ("level", -1), ">": ("level", 1)}
        if event.character in actions:
            event.stop()
            kind, step = actions[event.character]
            self.plugin.edit_section(kind, step)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.plugin.jump(event.option_index)


def register(api):
    app = api.app
    panel: dict = {"widget": None, "heads": []}

    def has_doc(_app) -> bool:
        return app.active_editor is not None

    def render(keep: int | None = None) -> None:
        widget: OutlineList | None = panel["widget"]
        editor = app.active_editor
        if widget is None or editor is None or not api.owns_panel:
            return
        heads = model.headings(editor.text)
        panel["heads"] = heads
        row = editor.cursor_location[0]
        current = max((i for i, h in enumerate(heads) if h.line <= row), default=None)
        options = []
        for h in heads:
            text = Text("  " * (h.level - 1))
            text.append(h.title or "(untitled)", style="bold" if h.level == 1 else "")
            options.append(Option(text))
        if not options:
            options = [Option(Text("No headings yet. Alt+1, 2 and 3 make one."), disabled=True)]
        highlighted = widget.highlighted if keep is None else keep
        widget.clear_options()
        widget.add_options(options)
        if heads:
            target = highlighted if highlighted is not None and highlighted < len(heads) else current
            widget.highlighted = target if target is not None else 0
        api.app.panel.set_title(f"Outline: {editor.doc.title}")

    class Plugin:
        def jump(self, index: int) -> None:
            editor = app.active_editor
            heads = panel["heads"]
            if editor is None or not 0 <= index < len(heads):
                return
            editor.cursor_location = (heads[index].line, 0)
            editor.scroll_cursor_visible(center=True)
            editor.focus()

        def edit_section(self, kind: str, step: int) -> None:
            editor = app.active_editor
            widget = panel["widget"]
            if editor is None or widget is None or widget.highlighted is None or not panel["heads"]:
                return
            index = widget.highlighted
            text = editor.text
            if kind == "move":
                result = model.move_section(text, index, step)
                if result is None:
                    app.status.flash("No section to swap with in that direction.")
                    return
                new_text, line = result
                app.replace_document_text(editor.doc, new_text)
                heads = model.headings(new_text)
                keep = next((i for i, h in enumerate(heads) if h.line == line), index)
            else:
                new_text = model.shift_level(text, index, step)
                if new_text is None:
                    app.status.flash("Headings go from level 1 to 6.")
                    return
                app.replace_document_text(editor.doc, new_text)
                keep = index
            render(keep)

    plugin = Plugin()

    @api.command("outline.show", "&Outline", "f8", menu="document", separator=True, enabled=has_doc,
                 description="Headings in the side panel: jump, move and promote sections")
    async def show(app):
        if api.owns_panel:
            api.hide_panel()
            return
        widget = OutlineList(plugin)
        panel["widget"] = widget
        await api.show_panel(widget, "Outline", HINT)
        render()

    @api.on("document_changed")
    def changed(app, doc):
        render()

    @api.on("document_activated")
    def activated(app, doc):
        render(keep=None)
