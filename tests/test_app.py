from pathlib import Path

from inkmill.app import InkmillApp
from inkmill.config import Settings, State
from inkmill.screens.dialogs import ConfirmDialog, FindDialog, InputDialog
from inkmill.screens.files import FileManagerScreen
from inkmill.widgets.menubar import MenuScreen


def make_app(tmp_path, paths=(), **settings):
    settings.setdefault("restore_session", False)
    settings.setdefault("recovery_interval", 0)
    return InkmillApp(
        paths,
        settings=Settings(**settings),
        state=State(tmp_path / "state.json"),
        load_plugins=False,
    )


async def test_typing_and_status(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press(*"Hello there world")
        await pilot.pause(0.6)
        doc = app.active_document
        assert doc.text == "Hello there world"
        assert doc.dirty
        right = str(app.status.query_one("#status-right").render())
        assert "3 words" in right and "Pg 1 Ln 1 Pos 18" in right


async def test_wordperfect_theme_is_default(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test():
        assert app.theme == "wordperfect"
        assert app.current_theme.background.lower() == "#0000aa"


async def test_menu_opens_navigates_and_runs_by_letter(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        assert not app.query_one("#menubar").display
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, MenuScreen)
        assert app.screen.index == 0
        await pilot.press("right", "right")
        assert app.screen.index == 2  # Format
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, MenuScreen)
        # Alt+D opens the Document menu, N runs Next Document.
        await pilot.press("ctrl+n")
        await pilot.pause()
        first, second = app.docs.docs
        assert app.active_document is second
        await pilot.press("alt+d")
        await pilot.pause()
        assert isinstance(app.screen, MenuScreen) and app.screen.index == 3
        await pilot.press("n")
        await pilot.pause()
        assert app.active_document is first


async def test_menu_enter_runs_highlighted(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f10")  # File menu, "New" highlighted
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.docs) == 2


async def test_command_keys_inactive_in_dialogs(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert isinstance(app.screen, InputDialog)
        await pilot.press("ctrl+n")  # must not create a document behind the dialog
        await pilot.pause()
        assert len(app.docs) == 1
        await pilot.press("escape")


async def test_bold_italic_and_heading(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press(*"word", "ctrl+shift+left")
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert app.active_document.text == "**word**"
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert app.active_document.text == "word"
        await pilot.press("alt+2")
        await pilot.pause()
        assert app.active_document.text == "## word"
        await pilot.press("end", "space", "ctrl+e", *"x")
        await pilot.pause()
        assert app.active_document.text == "## word *x*"


async def test_footnote_and_go_back(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press(*"A claim.")
        app.run_command("format.footnote")
        await pilot.pause()
        await pilot.press(*"Source")
        app.run_command("edit.go_back")
        await pilot.pause()
        await pilot.press(*" More.")
        await pilot.pause()
        assert app.active_document.text == "A claim.[^1] More.\n\n[^1]: Source"


async def test_table_insert_and_tidy(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        editor = app.active_editor
        editor.load_text("|a|bb|\n|-|-|\n|ccc|d|")
        app.active_document.text = editor.text
        editor.move_cursor((2, 1))
        await pilot.press("ctrl+backslash")
        await pilot.pause()
        assert app.active_document.text == "| a   | bb  |\n| --- | --- |\n| ccc | d   |"


async def test_find_and_replace_all(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press(*"cat dog cat")
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert isinstance(app.screen, FindDialog)
        await pilot.press(*"cat", "tab", *"bird")
        await pilot.click("#replace_all")
        await pilot.pause()
        assert app.active_document.text == "bird dog bird"


async def test_open_save_and_multiple_documents(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.txt"
    a.write_text("alpha\n")
    b.write_text("beta\n")
    app = make_app(tmp_path, [a, b])
    async with app.run_test(size=(100, 30)) as pilot:
        assert [d.path for d in app.docs] == [a, b]  # pristine untitled replaced
        assert app.active_document.format.id == "text"
        await pilot.press("f6")
        assert app.active_document.path == a
        await pilot.press("end", *" one")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert a.read_text() == "alpha one\n"
        assert not app.active_document.dirty


async def test_save_as_through_file_manager(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press(*"draft")
        await pilot.press("f12")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FileManagerScreen) and screen.mode == "save"
        screen.change_directory(tmp_path)
        name = screen.query_one("#fm-name")
        name.value = "novel"
        await pilot.press("enter")
        await pilot.pause()
        assert (tmp_path / "novel.md").read_text() == "draft\n"
        assert app.active_document.path == tmp_path / "novel.md"


async def test_file_manager_preview_mark_and_open(tmp_path):
    for name in ("one.md", "two.md", "three.txt"):
        (tmp_path / name).write_text(f"# {name}\n")
    (tmp_path / "sub").mkdir()
    app = make_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("f5")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FileManagerScreen)
        screen.change_directory(tmp_path)
        await pilot.pause()
        names = [e.name for e in screen.entries]
        assert names == ["..", "sub", "one.md", "three.txt", "two.md"]
        await pilot.press("down", "down")  # one.md
        await pilot.pause(0.3)
        assert "one.md" in str(screen.query_one("#fm-preview-title").render())
        await pilot.press("asterisk", "down", "asterisk")  # mark one.md and two.md
        assert screen.marked == {tmp_path / "one.md", tmp_path / "two.md"}
        await pilot.press("1")
        await pilot.pause()
        assert sorted(d.path.name for d in app.docs) == ["one.md", "two.md"]


async def test_file_manager_rename_updates_open_document(tmp_path):
    src = tmp_path / "old.md"
    src.write_text("x\n")
    app = make_app(tmp_path, [src])
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("f5")
        await pilot.pause()
        screen = app.screen
        screen.change_directory(tmp_path)
        await pilot.press("down")
        await pilot.press("3")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, InputDialog)
        dialog.query_one("Input").value = "new.md"
        await pilot.press("enter")
        await pilot.pause()
        assert (tmp_path / "new.md").exists() and not src.exists()
        assert app.docs.docs[0].path == tmp_path / "new.md"


async def test_close_dirty_document_asks(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press(*"unsaved")
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.press("c")  # cancel
        await pilot.pause()
        assert app.active_document.text == "unsaved"
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("n")  # discard
        await pilot.pause()
        assert app.active_document.text == ""


async def test_recovery_snapshot_and_restore(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press(*"precious words")
        await pilot.pause()
        app.snapshot_unsaved()
    snaps = app.recovery.list()
    assert len(snaps) == 1 and snaps[0].read() == "precious words"

    app2 = make_app(tmp_path)
    async with app2.run_test(size=(100, 30)) as pilot:
        app2.run_command("file.recover")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app2.active_document.text == "precious words"
        assert app2.recovery.list() == []


async def test_session_is_saved_and_restored(tmp_path):
    a = tmp_path / "a.md"
    a.write_text("a\n")
    state = State(tmp_path / "state.json")
    app = InkmillApp([a], settings=Settings(recovery_interval=0), state=state, load_plugins=False)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+q")
        await pilot.pause()
    assert State(tmp_path / "state.json").session == [str(a.resolve())]
    app2 = InkmillApp(settings=Settings(recovery_interval=0), state=State(tmp_path / "state.json"), load_plugins=False)
    async with app2.run_test():
        assert app2.active_document.path == a.resolve()


async def test_key_override_from_settings(tmp_path):
    app = make_app(tmp_path, keys={"file.new": "f2"})
    async with app.run_test() as pilot:
        await pilot.press("f2")
        await pilot.pause()
        assert len(app.docs) == 2


async def test_preview_writes_html_and_opens(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("inkmill.builtin.open_in_browser", lambda path, server: opened.append(path) or "test")
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press(*"# Hi")
        await pilot.press("f9")
        await pilot.pause()
    assert opened and opened[0].read_text().count("<h1") == 1
