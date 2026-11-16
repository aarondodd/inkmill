from textual.widgets import Markdown, OptionList

from pluginhelp import app_with, wait_for


def reader(app):
    from textual.containers import VerticalScroll

    return next(w for w in app.panel.query(VerticalScroll) if type(w).__name__ == "SideReader")


def shown_source(app) -> str:
    return reader(app).query_one(Markdown).source


async def test_pin_page_and_unpin(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("---\ntitle: Notes\n---\n# Places\nThe *harbor* town.\n")
    people = tmp_path / "people.md"
    people.write_text("# People\nLenora, the keeper.\n")
    draft = tmp_path / "draft.md"
    draft.write_text("Chapter one.\n")
    app = app_with(tmp_path, "reader", paths=[notes, people, draft])
    async with app.run_test(size=(140, 30)) as pilot:
        app.activate(app.docs.find_path(notes))
        await pilot.press("shift+f4")
        assert await wait_for(pilot, lambda: app.panel.visible and "harbor" in shown_source(app))
        # Pinning leaves the focus in the text, and front matter is not shown.
        assert app.focused is app.active_editor
        assert "title:" not in shown_source(app)
        assert "Notes (1 of 1)" in str(app.panel.query_one("#panel-title").render())

        app.activate(app.docs.find_path(people))
        await pilot.press("shift+f4")
        assert await wait_for(pilot, lambda: "Lenora" in shown_source(app))

        app.activate(app.docs.find_path(draft))
        await pilot.press("ctrl+t")
        assert app.panel_has_focus()
        await pilot.press("left")
        assert await wait_for(pilot, lambda: "harbor" in shown_source(app))
        await pilot.press("right_square_bracket")
        assert await wait_for(pilot, lambda: "Lenora" in shown_source(app))

        # The reader is read-only: typing changes nothing.
        await pilot.press("x", "y")
        assert app.docs.find_path(people).text == "# People\nLenora, the keeper.\n"

        await pilot.press("u")
        assert await wait_for(pilot, lambda: "harbor" in shown_source(app))
        await pilot.press("ctrl+t")
        assert app.focused is app.active_editor
        assert app.active_document.path == draft

        await pilot.press("f4")
        assert await wait_for(pilot, lambda: not app.panel.visible)
        await pilot.press("f4")
        assert await wait_for(pilot, lambda: app.panel.visible and "harbor" in shown_source(app))
        assert app.panel_has_focus()
        await pilot.press("e")
        assert await wait_for(pilot, lambda: app.active_document.path == notes)


async def test_list_follows_edits_and_closing(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("# Places\nThe harbor town.\n")
    draft = tmp_path / "draft.md"
    draft.write_text("Chapter one.\n")
    app = app_with(tmp_path, "reader", paths=[notes, draft])
    async with app.run_test(size=(140, 30)) as pilot:
        app.activate(app.docs.find_path(draft))
        # F4 with nothing pinned lists the open documents.
        await pilot.press("f4")
        assert await wait_for(pilot, lambda: len(app.screen_stack) > 1)
        options = app.screen.query_one(OptionList)
        index = next(i for i in range(options.option_count) if "notes.md" in str(options.get_option_at_index(i).prompt))
        options.highlighted = index
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: "harbor" in shown_source(app))

        # Unsaved changes to a pinned document show in the reader.
        app.activate(app.docs.find_path(notes))
        app.active_editor.insert("Gulls.\n", (2, 0))
        assert await wait_for(pilot, lambda: "Gulls." in shown_source(app))

        # W widens the panel and remembers it.
        await pilot.press("ctrl+t", "w")
        assert await wait_for(pilot, lambda: app.panel.has_class("-reader-wide"))
        assert app.settings.plugins["reader"]["wide"] is True
        await pilot.press("w")
        assert await wait_for(pilot, lambda: not app.panel.has_class("-reader-wide"))

        closing = app.docs.find_path(notes)
        closing.saved_text = closing.text
        await app.close_document(closing)
        assert await wait_for(pilot, lambda: not reader(app).plugin.pinned)
