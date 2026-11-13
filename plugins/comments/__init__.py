"""Comments & Track Changes, stored as CriticMarkup in the text itself.

Add Comment (Alt+C) annotates the selection, or drops a comment at the
cursor. Suggest Insertion, Deletion and Replacement record edits for someone
to accept or reject. Review Changes lists every comment and suggestion in
the side panel: Enter goes to it, A accepts, R rejects. A suggestion
followed directly by a comment ({~~old~>new~~}{>>why<<}) is one item, and
the comment goes with it. Accept All and Reject All finish a round.

Exports show the marks (``export = "show"``, the default), or apply them as
if every suggestion were accepted (``"final"``) or rejected (``"original"``);
comments are dropped in both clean modes.
"""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual import events
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from inkmill.screens.dialogs import ConfirmDialog, InputDialog

from . import critic

OWNER = "comments"
HINT = "Enter go  A accept  R reject  Ctrl+T text  Esc close"


class ReviewList(OptionList):
    def __init__(self, plugin) -> None:
        super().__init__()
        self.plugin = plugin

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id:
            self.plugin.go(int(event.option.id))

    def on_key(self, event: events.Key) -> None:
        key = (event.character or "").lower()
        if key in ("a", "r") and self.highlighted is not None:
            option = self.get_option_at_index(self.highlighted)
            if option.id:
                event.stop()
                self.plugin.resolve_one(int(option.id), accept=key == "a")


def register(api):
    app = api.app
    state: dict = {"widget": None, "marks": []}

    def has_doc(_app) -> bool:
        return app.active_editor is not None

    api.add_menu("review", "&Review")
    api.decoration_style("critic.add", lambda v: Style(underline=True, bold=True))
    api.decoration_style("critic.delete", lambda v: Style(strike=True))
    api.decoration_style("critic.note", lambda v: Style(italic=True, color=v.get("im-heading")))

    def mode() -> str:
        value = str(api.settings.get("export", "show"))
        return value if value in ("show", "final", "original") else "show"

    def extend(md) -> None:
        def preprocess(state_):
            current = mode()
            if current == "show":
                if critic.MARK.search(state_.src):
                    state_.src = critic.to_html(state_.src) + "\n\n" + critic.EXPORT_CSS
            else:
                state_.src = critic.resolve(state_.src, accept=current == "final")

        md.core.ruler.before("normalize", "criticmarkup", preprocess)

    api.markdown_extension(extend)

    class Service:
        """For other plugins: text with every suggestion accepted or rejected."""

        @staticmethod
        def final(text: str) -> str:
            return critic.resolve(text, accept=True)

        @staticmethod
        def original(text: str) -> str:
            return critic.resolve(text, accept=False)

        marks = staticmethod(critic.marks)

    api.provide("comments", Service())

    # -- highlighting --------------------------------------------------------

    def decorate() -> None:
        editor = app.active_editor
        if editor is None:
            return
        text = editor.text
        ranges = []
        for mark in critic.marks(text):
            style = {"add": "critic.add", "delete": "critic.delete"}.get(mark.kind, "critic.note")
            end = mark.end
            if mark.note and mark.kind in ("add", "delete", "replace"):
                # The reason comment after a suggested edit.
                end = text.rindex("{>>", mark.start, mark.end)
                ranges.append((editor.location_of(end), editor.location_of(mark.end), "critic.note"))
            if mark.kind == "replace":
                arrow = text.index("~>", mark.start)
                ranges.append((editor.location_of(mark.start), editor.location_of(arrow), "critic.delete"))
                ranges.append((editor.location_of(arrow), editor.location_of(end), "critic.add"))
            else:
                ranges.append((editor.location_of(mark.start), editor.location_of(end), style))
        editor.set_decorations(OWNER, ranges)

    def render_list() -> None:
        widget: ReviewList | None = state["widget"]
        editor = app.active_editor
        if widget is None or editor is None or not api.owns_panel:
            return
        found = critic.marks(editor.text)
        state["marks"] = found
        keep = widget.highlighted
        widget.clear_options()
        if not found:
            widget.add_option(Option("No comments or suggestions.", disabled=True))
        for i, mark in enumerate(found):
            row = editor.location_of(mark.start)[0]
            line = Text(f"{row + 1:>4} ", style="dim")
            line.append(mark.label())
            widget.add_option(Option(line, id=str(i)))
        if found:
            widget.highlighted = min(keep or 0, len(found) - 1)
        app.panel.set_title(f"Review: {len(found)} item(s)")

    @api.on("document_changed")
    def changed(app, doc):
        decorate()
        render_list()

    @api.on("document_activated")
    def activated(app, doc):
        decorate()
        render_list()

    @api.on("ready")
    def ready(app):
        decorate()

    # -- adding --------------------------------------------------------------

    def selection_range(editor):
        sel = editor.selection
        return sorted([sel.start, sel.end])

    @api.command("comments.add", "Add &Comment...", "alt+c", menu="review", enabled=has_doc,
                 description="Comment on the selection, or at the cursor")
    async def add_comment(app):
        editor = app.active_editor
        start, end = selection_range(editor)
        note = await app.push_screen_wait(InputDialog("Comment", "Comment:", ""))
        if not note:
            return
        note = note.replace("<<", "< <")
        if start != end:
            chosen = editor.document.get_text_range(start, end)
            editor.replace(f"{{=={chosen}==}}{{>>{note}<<}}", start, end)
        else:
            editor.insert(f"{{>>{note}<<}}", start)
        editor.focus()

    @api.command("comments.insert", "Suggest &Insertion...", menu="review", enabled=has_doc)
    async def suggest_insert(app):
        editor = app.active_editor
        start, end = selection_range(editor)
        added = await app.push_screen_wait(InputDialog("Suggest Insertion", "Text to add:", ""))
        if added:
            editor.insert(f"{{++{added}++}}", end)
            editor.focus()

    @api.command("comments.delete", "Suggest &Deletion", menu="review", enabled=has_doc)
    def suggest_delete(app):
        editor = app.active_editor
        start, end = selection_range(editor)
        if start == end:
            app.status.flash("Select the text to suggest deleting.")
            return
        chosen = editor.document.get_text_range(start, end)
        editor.replace(f"{{--{chosen}--}}", start, end)

    @api.command("comments.replace", "Suggest Re&placement...", menu="review", enabled=has_doc)
    async def suggest_replace(app):
        editor = app.active_editor
        start, end = selection_range(editor)
        if start == end:
            app.status.flash("Select the text to suggest replacing.")
            return
        chosen = editor.document.get_text_range(start, end)
        new = await app.push_screen_wait(InputDialog("Suggest Replacement", f"Replace {chosen[:40]!r} with:", chosen))
        if new is not None and new != chosen:
            editor.replace(f"{{~~{chosen}~>{new}~~}}", start, end)
            editor.focus()

    # -- reviewing -----------------------------------------------------------

    class Plugin:
        def go(self, index: int) -> None:
            editor = app.active_editor
            found = state["marks"]
            if editor is None or not 0 <= index < len(found):
                return
            mark = found[index]
            editor.select_range(editor.location_of(mark.start), editor.location_of(mark.end))
            editor.focus()

        def resolve_one(self, index: int, *, accept: bool) -> None:
            editor = app.active_editor
            found = state["marks"]
            if editor is None or not 0 <= index < len(found):
                return
            mark = found[index]
            replacement = mark.accepted() if accept else mark.rejected()
            editor.replace(replacement, editor.location_of(mark.start), editor.location_of(mark.end))
            decorate()
            render_list()

    plugin = Plugin()

    @api.command("comments.review", "&Review Changes", menu="review", separator=True, enabled=has_doc,
                 description="Every comment and suggestion in the side panel")
    async def review(app):
        if api.owns_panel:
            api.hide_panel()
            return
        widget = ReviewList(plugin)
        state["widget"] = widget
        await api.show_panel(widget, "Review", HINT)
        render_list()

    async def resolve_all(accept: bool) -> None:
        editor = app.active_editor
        count = len(critic.marks(editor.text))
        if not count:
            app.status.flash("No comments or suggestions here.")
            return
        verb = "Accept" if accept else "Reject"
        answer = await app.push_screen_wait(ConfirmDialog(
            f"{verb} All", f"{verb} all {count} suggestion(s) and remove every comment? Ctrl+Z undoes it."
        ))
        if answer == "yes":
            app.replace_document_text(editor.doc, critic.resolve(editor.text, accept=accept))
            decorate()
            render_list()

    @api.command("comments.accept_all", "&Accept All", menu="review", enabled=has_doc)
    async def accept_all(app):
        await resolve_all(True)

    @api.command("comments.reject_all", "Re&ject All", menu="review", enabled=has_doc)
    async def reject_all(app):
        await resolve_all(False)
