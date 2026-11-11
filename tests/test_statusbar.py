from rich.cells import cell_len

from inkmill.widgets.statusbar import clip_path

from test_app import make_app


def test_clip_path_fits_unchanged():
    assert clip_path("~/notes/a.md", 40) == "~/notes/a.md"


def test_clip_path_drops_leading_folders_whole():
    text = "~/writing/novels/the-long-night/chapters/the-crossing.md *"
    clipped = clip_path(text, 30)
    assert clipped == ".../chapters/the-crossing.md *"
    assert cell_len(clipped) <= 30


def test_clip_path_cuts_long_name_from_the_left():
    text = "~/a/an-extremely-long-chapter-file-name.md"
    clipped = clip_path(text, 20)
    assert clipped.startswith("...") and clipped.endswith("file-name.md")
    assert cell_len(clipped) == 20


def test_clip_path_windows_separators():
    clipped = clip_path(r"D:\Books\Novel\Part One\chapter-01.md", 26)
    assert clipped == r"...\Part One\chapter-01.md"


def test_clip_path_tiny_width():
    assert clip_path("~/a/b.md", 0) == ""
    assert clip_path("~/a/b.md", 3) == ".md"


async def test_status_bar_shows_end_of_long_path(tmp_path):
    folder = tmp_path / "very-long-folder-name" / "another-long-folder" / "chapters"
    folder.mkdir(parents=True)
    path = folder / "chapter-twelve.md"
    path.write_text("Hello\n")
    app = make_app(tmp_path, paths=[path])
    async with app.run_test(size=(60, 12)) as pilot:
        app.status.clear_flash()
        await pilot.pause()
        left = app.status.query_one("#status-left")
        shown = str(left.render())
        assert shown.endswith("chapter-twelve.md")
        assert shown.startswith("...")


async def test_cursor_stays_visible_when_typing_wraps_past_bottom(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(40, 10)) as pilot:
        editor = app.active_editor
        hidden = 0
        for ch in "lorem ipsum dolor sit amet consectetur " * 12:
            await pilot.press("space" if ch == " " else ch)
            _, y = editor.cursor_screen_offset
            region = editor.content_region
            if not (region.y <= y < region.bottom):
                hidden += 1
        assert hidden == 0
