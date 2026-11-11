import re
from pathlib import Path

from inkmill import richtext
from inkmill.screens.reading import ReadingScreen, reading_text
from inkmill.themes import BUILTIN_THEMES, syntax_theme

from test_app import make_app


def styled(line, spans, name):
    return [line[s:e] for s, e, n in spans if n == name]


def spans_for(text):
    lines = text.split("\n")
    return lines, richtext.line_spans(lines)


def test_inline_emphasis_and_markers():
    line = "Some **bold**, *it*, _it_, ***both***, ~~gone~~ and ==hi=="
    spans = richtext.inline_spans(line)
    assert styled(line, spans, "rich.bold") == ["bold"]
    assert styled(line, spans, "rich.italic") == ["it", "it"]
    assert styled(line, spans, "rich.bold_italic") == ["both"]
    assert styled(line, spans, "rich.strike") == ["gone"]
    assert styled(line, spans, "rich.highlight") == ["hi"]
    assert "**" in styled(line, spans, "rich.marker")


def test_inline_code_links_and_footnotes_are_not_emphasis():
    line = "`a*b*c` [label **x**](http://e.com/a_b_c) snake_case_name [^2] 2 * 3 * 4"
    spans = richtext.inline_spans(line)
    assert styled(line, spans, "rich.code") == ["a*b*c"]
    assert styled(line, spans, "rich.link") == ["label **x**"]
    assert styled(line, spans, "rich.bold") == ["x"]
    assert styled(line, spans, "rich.footnote") == ["[^2]"]
    assert styled(line, spans, "rich.italic") == []


def test_escaped_markers_stay_plain():
    line = r"\*not italic\*"
    assert styled(line, richtext.inline_spans(line), "rich.italic") == []


def test_blocks():
    text = "\n".join([
        "---", "title: T", "---",
        "# One", "## Two", "> quote *x*", "- [x] done", "- [ ] todo", "1. item",
        "", "```", "**not bold**", "```",
        "Setext", "------",
        "", "---",
        "| A | B |", "|---|---|", "| 1 | 2 |",
        "[^1]: note",
    ])
    lines, out = spans_for(text)
    assert out[0] == out[1] == out[2] == [(0, None, "rich.frontmatter")]
    assert styled(lines[3], out[3], "rich.h1") == ["One"]
    assert styled(lines[4], out[4], "rich.heading") == ["Two"]
    assert styled(lines[5], out[5], "rich.quote") == ["quote *x*"]
    assert styled(lines[6], out[6], "rich.done") == ["done"]
    assert styled(lines[7], out[7], "rich.done") == []
    assert styled(lines[8], out[8], "rich.list") == ["1."]
    assert out[11] == [(0, None, "rich.code")]
    assert out[13][0] == (0, None, "rich.heading") and out[14] == [(0, None, "rich.marker")]
    assert out[16] == [(0, None, "rich.marker")]  # horizontal rule
    assert [s.strip() for s in styled(lines[17], out[17], "rich.table_header")] == ["A", "B"]
    assert out[18] == [(0, None, "rich.marker")]
    assert "rich.table_header" not in {n for _, _, n in out[19]}
    assert styled(lines[20], out[20], "rich.footnote") == ["[^1]:"]


def test_every_rich_style_is_in_every_theme():
    source = Path(richtext.__file__).read_text()
    names = set(re.findall(r'"(rich\.[a-z_0-9]+)"', source)) | {richtext.MARKER}
    for theme in BUILTIN_THEMES:
        styles = syntax_theme(theme).syntax_styles
        assert names <= set(styles), names - set(styles)


def test_cursor_cell_round_trip():
    row = "| Annette | Lead |"
    col = row.index("ette")
    cell, offset = richtext.cursor_cell(row, col)
    assert (cell, offset) == (0, 3)
    assert richtext.cursor_column(row, cell, offset) == col


def test_table_needs_tidy_requires_separator():
    assert richtext.table_needs_tidy(["| a | bb |", "| c | d |"], 0) is None
    found = richtext.table_needs_tidy(["| a | bb |", "|---|---|", "| ccc | d |"], 2)
    assert found is not None and found[:2] == (0, 2)
    assert richtext.table_needs_tidy(found[2], 0) is None


def test_reading_text_keeps_line_count():
    text = "---\ntitle: X\n---\nA note.[^1] Code `[^2]`\n\n- [x] done\n- [ ] todo\n\n[^1]: First.\n[^n]: Named."
    out = reading_text(text)
    assert out.count("\n") == text.count("\n")
    lines = out.split("\n")
    assert lines[:3] == ["", "", ""]
    assert lines[3] == "A note.¹ Code `[^2]`"
    assert lines[5] == "- [x] done" and lines[6] == "- [ ] todo"
    assert lines[8] == "¹ First.\\" and lines[9] == "[n] Named."


def test_reading_text_leaves_code_blocks_alone():
    text = "```\n[^1]: not a note\n- [ ] not a task\n```"
    assert reading_text(text) == text


TABLE_DOC = "Intro\n\n| Name | Role |\n|---|---|\n| Ann | Lead |\n\nEnd\n"


async def test_rich_view_toggle_applies_and_persists(tmp_path):
    md = tmp_path / "a.md"
    md.write_text("Some **bold** text\n")
    txt = tmp_path / "b.txt"
    txt.write_text("Some **bold** text\n")
    app = make_app(tmp_path, paths=[md, txt])
    async with app.run_test(size=(80, 20)) as pilot:
        editors = list(app.query("InkEditor"))
        assert not any(e.rich for e in editors)
        app.run_command("view.rich")
        await pilot.pause()
        assert app.settings.rich_view
        by_ext = {e.doc.path.suffix: e for e in editors}
        assert by_ext[".md"].rich and not by_ext[".txt"].rich
        names = {n for _, _, n in by_ext[".md"]._highlights[0]}
        assert "rich.bold" in names
        app.run_command("view.rich")
        await pilot.pause()
        assert not by_ext[".md"].rich
        assert not any(n.startswith("rich.") for _, _, n in by_ext[".md"]._highlights[0])


async def test_table_tidies_while_typing_and_undo_does_not_loop(tmp_path):
    path = tmp_path / "t.md"
    path.write_text(TABLE_DOC)
    app = make_app(tmp_path, paths=[path], rich_view=True)
    async with app.run_test(size=(80, 20)) as pilot:
        editor = app.active_editor
        editor.move_cursor((4, 5))
        await pilot.pause()
        await pilot.press(*"ette")
        await pilot.pause(0.3)
        lines = editor.document.lines
        assert lines[2:5] == ["| Name    | Role |", "| ------- | ---- |", "| Annette | Lead |"]
        assert editor.cursor_location == (4, lines[4].index(" | Lead"))
        before = editor.text
        await pilot.press("ctrl+z")
        await pilot.pause(0.3)
        assert editor.text != before
        await pilot.press("ctrl+z")
        await pilot.pause(0.3)
        await pilot.press("ctrl+z")
        await pilot.pause(0.3)
        assert "Annette" not in editor.text


async def test_raw_view_does_not_tidy(tmp_path):
    path = tmp_path / "t.md"
    path.write_text(TABLE_DOC)
    app = make_app(tmp_path, paths=[path])
    async with app.run_test(size=(80, 20)) as pilot:
        editor = app.active_editor
        editor.move_cursor((4, 5))
        await pilot.press(*"ette")
        await pilot.pause(0.3)
        assert editor.document.lines[4] == "| Annette | Lead |"
        assert editor.document.lines[2] == "| Name | Role |"


async def test_reading_view_opens_at_cursor_and_closes(tmp_path):
    body = "# Top\n\n" + "\n\n".join(f"Paragraph {i}." for i in range(60)) + "\n\n## Target\n\nLast words.\n"
    path = tmp_path / "r.md"
    path.write_text(body)
    app = make_app(tmp_path, paths=[path])
    async with app.run_test(size=(80, 20)) as pilot:
        editor = app.active_editor
        target = editor.document.lines.index("## Target")
        editor.move_cursor((target, 0))
        await pilot.press("shift+f7")
        await pilot.pause(0.5)
        screen = app.screen
        assert isinstance(screen, ReadingScreen)
        assert screen.query_one("#reading-scroll").scroll_y > 0
        assert screen.block_for_row(target).source_range[0] == target
        before = editor.text
        await pilot.press(*"abc")
        assert editor.text == before  # read-only
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ReadingScreen)
        await pilot.press("shift+f7")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ReadingScreen)
        await pilot.press("shift+f7")
        await pilot.pause()
        assert not isinstance(app.screen, ReadingScreen)
        assert app.focused is editor


def test_emphasis_colors_in_syntax_theme():
    from inkmill.themes import WORDPERFECT

    on = syntax_theme(WORDPERFECT).syntax_styles
    off = syntax_theme(WORDPERFECT, emphasis_colors=False).syntax_styles
    assert on["rich.bold"].bold and on["rich.bold"].color is not None
    assert on["rich.italic"].italic and on["rich.italic"].color is not None
    assert on["rich.bold"].color != on["rich.italic"].color
    assert off["rich.bold"].bold and off["rich.bold"].color is None
    assert off["rich.italic"].italic and off["rich.italic"].color is None


def test_derived_emphasis_colors_are_readable():
    from textual.color import Color
    from textual.theme import BUILTIN_THEMES as TEXTUAL_THEMES

    from inkmill.themes import _contrast_ratio, derive_variables

    for theme in list(TEXTUAL_THEMES.values()) + list(BUILTIN_THEMES):
        values = {**derive_variables(theme), **theme.variables}
        bg = Color.parse(theme.background or "#000000")
        fg = Color.parse(theme.foreground or "#ffffff")
        floor = min(4.5, _contrast_ratio(fg, bg))
        for key in ("im-bold", "im-italic"):
            assert _contrast_ratio(Color.parse(values[key]), bg) >= floor - 0.01, (theme.name, key)


async def test_emphasis_colors_toggle(tmp_path):
    path = tmp_path / "e.md"
    path.write_text("Some **bold** and *it*.\n")
    app = make_app(tmp_path, paths=[path], rich_view=True)
    async with app.run_test(size=(80, 20)) as pilot:
        editor = app.active_editor
        assert editor._theme.syntax_styles["rich.bold"].color is not None
        app.run_command("view.emphasis_colors")
        await pilot.pause()
        assert not app.settings.emphasis_colors
        assert editor._theme.syntax_styles["rich.bold"].color is None
        await pilot.press("shift+f7")
        await pilot.pause(0.3)
        assert app.screen.has_class("-plain-emphasis")
