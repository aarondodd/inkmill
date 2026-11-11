import pytest
from textual.widgets.text_area import Selection

from test_app import make_app

# (text, selected columns on row 0, command, expected text, expected selection or cursor)
CASES = [
    ("", (0, 0), "format.italic", "*italic text*", ("sel", "italic text")),
    ("", (0, 0), "format.bold", "**bold text**", ("sel", "bold text")),
    ("", (0, 0), "format.code", "`code`", ("sel", "code")),
    ("", (0, 0), "format.strike", "~~struck text~~", ("sel", "struck text")),
    ("end. ", (5, 5), "format.italic", "end. *italic text*", ("sel", "italic text")),
    ("say word now", (6, 6), "format.italic", "say *word* now", ("cur", (0, 7))),
    ("say word now", (8, 8), "format.bold", "say **word** now", ("cur", (0, 10))),
    ("say *word* now", (6, 6), "format.italic", "say word now", ("cur", (0, 5))),
    ("say **word** now", (7, 7), "format.italic", "say ***word*** now", None),
    ("say ***word*** now", (8, 8), "format.italic", "say **word** now", None),
    ("say ***word*** now", (8, 8), "format.bold", "say *word* now", None),
    ("say **word** now", (4, 12), "format.italic", "say ***word*** now", ("sel", "word")),
    ("say **word** now", (4, 12), "format.bold", "say word now", ("sel", "word")),
    ("say word now", (4, 8), "format.code", "say `word` now", ("sel", "word")),
    ("don't", (2, 2), "format.italic", "*don't*", None),
    ("a **** b", (4, 4), "format.bold", "a  b", None),
    # Right before the closing marker: step out rather than unwrap.
    ("She was *tired* x", (14, 14), "format.italic", "She was *tired* x", ("cur", (0, 15))),
    ("**done**", (6, 6), "format.bold", "**done**", ("cur", (0, 8))),
    ("***both***", (7, 7), "format.italic", "***both***", ("cur", (0, 8))),
]


@pytest.mark.parametrize("text,cols,command,expected,check", CASES)
async def test_format_wrap(tmp_path, text, cols, command, expected, check):
    app = make_app(tmp_path)
    async with app.run_test(size=(80, 10)) as pilot:
        editor = app.active_editor
        editor.text = text
        editor.selection = Selection((0, cols[0]), (0, cols[1]))
        await pilot.pause()
        app.run_command(command)
        await pilot.pause()
        assert editor.text == expected
        if check and check[0] == "sel":
            start, end = sorted(editor.selection)
            assert editor.get_text_range(start, end) == check[1]
        if check and check[0] == "cur":
            assert editor.cursor_location == check[1]


async def test_typing_replaces_the_placeholder(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.press("ctrl+e", *"slanted")
        await pilot.pause()
        assert app.active_document.text == "*slanted*"


async def test_toggle_twice_types_plain_after(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.press(*"She was ", "ctrl+e", *"tired", "ctrl+e", *" today")
        await pilot.pause()
        assert app.active_document.text == "She was *tired* today"


async def test_selection_keeps_its_colors_in_rich_view(tmp_path):
    app = make_app(tmp_path, rich_view=True)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()
        editor = app.active_editor
        names = [h[2] for h in editor._highlights[0]]
        assert names[-1] == "rich.selected"
        await pilot.press(*"x")
        await pilot.pause()
        assert "rich.selected" not in [h[2] for h in editor._highlights[0]]
