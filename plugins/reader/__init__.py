"""Side Reader: open documents pinned in the side panel, formatted and
read-only, to refer to while writing another.

Shift+F4 pins the document you are in; F4 shows or hides the reader. In the
reader, Left and Right (or [ and ]) page through the pinned documents, L
lists every open document to pin one, U unpins, E edits the one shown, W
widens the panel, Ctrl+T goes back to the text and Esc closes. A pinned
document follows its unsaved changes and leaves the reader when it is
closed.
"""

from __future__ import annotations

import re

from rich.text import Text
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Markdown, Static

from inkmill.screens.dialogs import ChoiceDialog
from inkmill.screens.reading import reading_text

HINT = "<- -> pinned  L list  U unpin  E edit  W wide  Esc close"
EMPTY = "Nothing pinned. L lists the open documents; Shift+F4 in a document pins it."


class SideReader(VerticalScroll):
    """The pinned documents, one at a time."""

    # Unscoped so the rules can reach the panel around the reader.
    SCOPED_CSS = False
    DEFAULT_CSS = """
    SidePanel.-reader-wide { width: 50%; }
    SidePanel.-reader-wide.-narrow { width: 100%; }
    SideReader { padding: 0 1; }
    SideReader Markdown { background: $im-input-bg; margin: 0; padding: 0; }
    SideReader MarkdownBlock > .strong { color: $im-bold; }
    SideReader MarkdownBlock > .em { color: $im-italic; }
    SideReader.-plain-emphasis MarkdownBlock > .strong { color: $foreground; }
    SideReader.-plain-emphasis MarkdownBlock > .em { color: $foreground; }
    SideReader #reader-plain, SideReader #reader-empty { height: auto; }
    SideReader #reader-empty { color: $im-input-fg 70%; text-style: italic; }
    """

    BINDINGS = [
        Binding("left,left_square_bracket", "step(-1)", show=False),
        Binding("right,right_square_bracket", "step(1)", show=False),
        Binding("l", "pick", show=False),
        Binding("u", "unpin", show=False),
        Binding("e,enter", "edit", show=False),
        Binding("w", "wide", show=False),
    ]

    can_focus = True

    def __init__(self, plugin) -> None:
        super().__init__()
        self.plugin = plugin

    def compose(self):
        yield Static(EMPTY, id="reader-empty")
        yield Markdown(id="reader-doc", open_links=False)
        yield Static("", id="reader-plain")

    def on_mount(self) -> None:
        self.set_class(not self.app.settings.emphasis_colors, "-plain-emphasis")
        self.set_wide(bool(self.plugin.settings.get("wide", False)))

    def on_unmount(self) -> None:
        if self.parent is not None:
            self.set_wide(False)

    def set_wide(self, wide: bool) -> None:
        try:
            self.app.panel.set_class(wide, "-reader-wide")
        except Exception:
            pass
        self.app.call_after_refresh(self.app._repaint_editors)

    async def render_doc(self, doc, *, keep_scroll: bool = False) -> None:
        empty = self.query_one("#reader-empty", Static)
        markdown = self.query_one("#reader-doc", Markdown)
        plain = self.query_one("#reader-plain", Static)
        empty.display = doc is None
        markdown.display = doc is not None and doc.format.markdown
        plain.display = doc is not None and not doc.format.markdown
        if doc is None:
            return
        y = self.scroll_y if keep_scroll else self.plugin.scroll.get(doc.id, 0)
        if doc.format.markdown:
            await markdown.update(reading_text(doc.text))
        else:
            plain.update(Text(doc.text))
        self.call_after_refresh(self.scroll_to, y=y, animate=False)

    def remember_scroll(self) -> None:
        doc = self.plugin.current
        if doc is not None:
            self.plugin.scroll[doc.id] = self.scroll_y

    # -- keys ------------------------------------------------------------------

    def action_step(self, step: int) -> None:
        self.plugin.step(step)

    def action_pick(self) -> None:
        self.plugin.pick()

    def action_unpin(self) -> None:
        self.plugin.unpin()

    def action_edit(self) -> None:
        self.plugin.edit()

    def action_wide(self) -> None:
        wide = not self.plugin.settings.get("wide", False)
        self.plugin.settings["wide"] = wide
        self.plugin.save_settings()
        self.set_wide(wide)

    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        event.stop()
        href = event.href
        if re.match(r"^(https?|ftp|mailto):", href):
            from inkmill.system import open_url

            try:
                open_url(href)
            except RuntimeError as exc:
                self.app.notify(str(exc), severity="warning")
        else:
            self.app.notify(f"Link: {href}", timeout=4)


def register(api):
    app = api.app

    class Plugin:
        def __init__(self) -> None:
            self.pinned: list = []
            self.index = 0
            self.scroll: dict[int, float] = {}
            self.widget: SideReader | None = None

        settings = property(lambda self: api.settings)

        def save_settings(self) -> None:
            api.save_settings()

        @property
        def current(self):
            return self.pinned[self.index] if self.pinned else None

        @property
        def showing(self) -> bool:
            return self.widget is not None and api.owns_panel

        async def open(self, *, focus: bool = True) -> None:
            if not self.showing:
                self.widget = SideReader(self)
                await api.show_panel(self.widget, "Side Reader", HINT, focus=focus)
            elif focus:
                app.panel.focus_content()
            await self.refresh()

        async def refresh(self, *, keep_scroll: bool = False) -> None:
            if not self.showing:
                return
            doc = self.current
            if doc is None:
                app.panel.set_title("Side Reader")
            else:
                name = (doc.display_title if app.settings.show_titles else "") or doc.title
                app.panel.set_title(f"Reading: {name} ({self.index + 1} of {len(self.pinned)})")
            await self.widget.render_doc(doc, keep_scroll=keep_scroll)

        def show_doc(self, doc) -> None:
            """Pin ``doc`` if it is not pinned yet, and show it."""
            if self.showing:
                self.widget.remember_scroll()
            if doc not in self.pinned:
                self.pinned.append(doc)
            self.index = self.pinned.index(doc)

        def step(self, step: int) -> None:
            if len(self.pinned) < 2:
                app.status.flash("Only one document is pinned. L lists the open ones." if self.pinned
                                 else "Nothing pinned yet.")
                return
            self.widget.remember_scroll()
            self.index = (self.index + step) % len(self.pinned)
            app.run_worker(self.refresh(), group="reader", exclusive=True)

        def pick(self) -> None:
            items = []
            for i, doc in enumerate(app.docs, 1):
                title = doc.display_title if app.settings.show_titles else ""
                where = f"{title}  ({doc.display_path})" if title else doc.display_path
                mark = "  [pinned]" if doc in self.pinned else ""
                items.append((str(doc.id), f"Doc {i}  {where}{mark}"))
            current = self.current or app.active_document

            def chosen(choice) -> None:
                doc = next((d for d in app.docs if str(d.id) == choice), None) if choice else None
                if doc is not None:
                    self.show_doc(doc)
                app.run_worker(self.open(), group="reader", exclusive=True)

            app.push_screen(ChoiceDialog("Read which document?", items, str(current.id) if current else None), chosen)

        def unpin(self) -> None:
            doc = self.current
            if doc is None:
                return
            self.drop(doc)
            app.status.flash(f"Unpinned {doc.title}.")

        def drop(self, doc) -> None:
            if doc not in self.pinned:
                return
            at = self.pinned.index(doc)
            self.pinned.remove(doc)
            self.scroll.pop(doc.id, None)
            if at < self.index or self.index >= len(self.pinned):
                self.index = max(0, self.index - 1)
            app.run_worker(self.refresh(), group="reader", exclusive=True)

        def edit(self) -> None:
            doc = self.current
            if doc is not None and doc in app.docs:
                app.activate(doc)

    plugin = Plugin()

    def has_doc(_app) -> bool:
        return app.active_document is not None

    @api.command("reader.show", "Side &Reader", "f4", menu="document", separator=True,
                 description="Show or hide the pinned documents, formatted and read-only, in the side panel")
    async def show(app):
        if plugin.showing:
            plugin.widget.remember_scroll()
            api.hide_panel()
            return
        await plugin.open()
        if not plugin.pinned:
            plugin.pick()

    @api.command("reader.pin", "Pin to Sid&e Reader", "shift+f4", menu="document", enabled=has_doc,
                 description="Pin the current document in the Side Reader and keep writing")
    async def pin(app):
        doc = app.active_document
        if doc is None:
            return
        plugin.show_doc(doc)
        await plugin.open(focus=False)
        app.status.flash(f"Pinned {doc.title}. F4 shows or hides the reader, Ctrl+T goes to it.")

    @api.on("document_changed")
    async def changed(app, doc):
        if plugin.showing and doc is plugin.current:
            await plugin.refresh(keep_scroll=True)

    @api.on("document_reloaded")
    async def reloaded(app, doc):
        if plugin.showing and doc is plugin.current:
            await plugin.refresh(keep_scroll=True)

    @api.on("document_closed")
    def closed(app, doc):
        plugin.drop(doc)
