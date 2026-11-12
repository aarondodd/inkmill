"""Front matter titles in List Files, the status line and the document list."""

from rich.cells import cell_len

from inkmill.documents import read_title, title_from_text
from inkmill.screens.files import FileManagerScreen, list_directory
from inkmill.widgets.statusbar import fit_title

from test_app import make_app

TITLED = '---\ntitle: "The Crossing"\nstatus: draft\n---\n# Chapter 3\n\nText.\n'


def test_title_from_text():
    assert title_from_text(TITLED) == "The Crossing"
    assert title_from_text("---\ntitle:   Two   spaces \n---\n") == "Two spaces"
    assert title_from_text("# Heading only\n") == ""
    assert title_from_text("---\ntitle: [a, b]\n---\n") == ""
    assert title_from_text("---\r\ntitle: Windows\r\n---\r\n") == "Windows"
    # A block with no closing fence near the start is not front matter.
    assert title_from_text("---\ntitle: Open\n" + "x\n" * 5000) == ""


def test_read_title_follows_file_changes(tmp_path):
    path = tmp_path / "ch.md"
    path.write_text(TITLED)
    assert read_title(path) == "The Crossing"
    path.write_text("---\ntitle: Renamed chapter\n---\n")
    assert read_title(path) == "Renamed chapter"
    assert read_title(tmp_path / "missing.md") == ""
    (tmp_path / "bin.md").write_bytes(b"---\ntitle: x\n---\n\0\0")
    assert read_title(tmp_path / "bin.md") == ""


def test_list_directory_titles_sort_and_search(tmp_path):
    (tmp_path / "a-file.md").write_text("---\ntitle: Zebra\n---\n")
    (tmp_path / "b-file.md").write_text("no title\n")
    (tmp_path / "c-file.txt").write_text("---\ntitle: Apple\n---\n")
    plain = list_directory(tmp_path)
    assert [e.shown for e in plain] == ["a-file.md", "b-file.md", "c-file.txt"]
    titled = list_directory(tmp_path, title_extensions={".md"})
    # Only Markdown files carry titles; the name sort uses what is shown.
    assert [e.shown for e in titled] == ["b-file.md", "c-file.txt", "Zebra"]
    assert [e.name for e in titled] == ["b-file.md", "c-file.txt", "a-file.md"]
    found = list_directory(tmp_path, title_extensions={".md"}, name_filter="zeb")
    assert [e.name for e in found] == ["a-file.md"]
    found = list_directory(tmp_path, title_extensions={".md"}, name_filter="a-fi")
    assert [e.name for e in found] == ["a-file.md"]


def test_fit_title_keeps_title_and_end_of_path():
    path = "~/writing/novel/chapters/the-crossing.md *"
    title, rest = fit_title("The Crossing", path, 80)
    assert (title, rest) == ("The Crossing", path)
    title, rest = fit_title("The Crossing", path, 40)
    assert title == "The Crossing"
    assert rest.endswith("the-crossing.md *") and rest.startswith("...")
    assert cell_len(title) + 2 + cell_len(rest) <= 40
    long = "A Very Long Chapter Title That Goes On And On"
    title, rest = fit_title(long, path, 40)
    assert cell_len(title) == 20 and title.endswith("...")
    assert cell_len(title) + 2 + cell_len(rest) <= 40
    assert fit_title("", path, 20)[0] == ""
    # Too narrow for both: the title alone, keeping the unsaved marker.
    assert fit_title("Arrival at Port Ellery", "~/book/ch-01.md *", 16) == ("Arrival at... *", "")
    assert fit_title("The Crossing", "~/book/ch-03.md", 20) == ("The Crossing", "")


async def test_status_line_and_document_list_show_title(tmp_path):
    path = tmp_path / "ch-03.md"
    path.write_text(TITLED)
    app = make_app(tmp_path, paths=[path])
    async with app.run_test(size=(100, 20)) as pilot:
        app.status.clear_flash()
        await pilot.pause()
        left = str(app.status.query_one("#status-left").render())
        assert left.startswith("The Crossing  ") and left.endswith("ch-03.md")
        assert app.sub_title == "The Crossing"

        app.run_command("view.titles")
        await pilot.pause()
        assert not app.settings.show_titles
        app.status.clear_flash()
        await pilot.pause()
        left = str(app.status.query_one("#status-left").render())
        assert "The Crossing" not in left and left.endswith("ch-03.md")
        assert app.sub_title == "ch-03.md"


async def test_status_line_follows_title_edits(tmp_path):
    path = tmp_path / "note.md"
    path.write_text("---\ntitle: First\n---\nBody\n")
    app = make_app(tmp_path, paths=[path])
    async with app.run_test(size=(100, 20)) as pilot:
        editor = app.active_editor
        editor.move_cursor((1, len("title: First")))
        await pilot.press(*" draft")
        await pilot.pause(0.2)
        app.status.clear_flash()
        await pilot.pause()
        assert str(app.status.query_one("#status-left").render()).startswith("First draft  ")


async def test_file_manager_shows_titles_and_toggles(tmp_path):
    app_dir, tmp_path = tmp_path, tmp_path / "book"
    tmp_path.mkdir()
    (tmp_path / "ch-01.md").write_text("---\ntitle: Arrival\n---\n")
    (tmp_path / "ch-02.md").write_text("No front matter.\n")
    app = make_app(app_dir)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("f5")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FileManagerScreen)
        screen.change_directory(tmp_path)
        await pilot.pause()
        assert [e.shown for e in screen.entries] == ["..", "Arrival", "ch-02.md"]
        await pilot.press("down")
        await pilot.pause(0.3)
        assert "Arrival  (ch-01.md)" in str(screen.query_one("#fm-preview-title").render())
        await pilot.press("i")
        await pilot.pause()
        assert not app.settings.show_titles
        assert [e.shown for e in screen.entries] == ["..", "ch-01.md", "ch-02.md"]
        # The cursor stays on the same file across the toggle.
        assert screen.current_path() == tmp_path / "ch-01.md"
        await pilot.press("i")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.active_document.path == tmp_path / "ch-01.md"


async def test_save_as_uses_file_name_not_title(tmp_path):
    (tmp_path / "ch-01.md").write_text("---\ntitle: Arrival\n---\n")
    app = make_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("f12")
        await pilot.pause()
        screen = app.screen
        screen.change_directory(tmp_path)
        await pilot.pause()
        screen.query_one("#fm-table").focus()
        await pilot.press("down")
        await pilot.pause()
        assert screen.query_one("#fm-name").value == "ch-01.md"


async def test_toggling_titles_keeps_the_highlighted_file(tmp_path):
    app_dir, folder = tmp_path, tmp_path / "book"
    folder.mkdir()
    (folder / "a.md").write_text("---\ntitle: Zebra\n---\n")
    (folder / "b.md").write_text("plain\n")
    app = make_app(app_dir)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("f5")
        await pilot.pause()
        screen = app.screen
        screen.change_directory(folder)
        await pilot.pause()
        assert [e.shown for e in screen.entries] == ["..", "b.md", "Zebra"]
        await pilot.press("down")  # b.md, which moves from row 1 to row 2
        await pilot.press("i")
        await pilot.pause()
        assert [e.shown for e in screen.entries] == ["..", "a.md", "b.md"]
        assert screen.current_path() == folder / "b.md"


async def test_long_title_fits_the_list_pane(tmp_path):
    folder = tmp_path / "book"
    folder.mkdir()
    (folder / "ch.md").write_text("---\ntitle: " + "A Very Long Chapter Title " * 3 + "\n---\n")
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f5")
        await pilot.pause()
        screen = app.screen
        screen.change_directory(folder)
        await pilot.pause(0.3)
        table = screen.query_one("#fm-table")
        assert table.virtual_size.width <= table.scrollable_content_region.width
