import importlib.util
import sys
from pathlib import Path

from inkmill import frontmatter as fm
from inkmill.app import InkmillApp
from inkmill.config import Settings, State

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"


def load_model():
    spec = importlib.util.spec_from_file_location("binder_model_under_test", PLUGINS / "binder" / "model.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


model = load_model()


def disk_read(path: Path):
    try:
        return path.read_text()
    except OSError:
        return None


def novel(tmp_path):
    """the-long-night.md with three chapters in chapters/."""
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    binder = tmp_path / "the-long-night.md"
    binder.write_text(
        "---\ntitle: The Long Night\nauthor: A. Writer\ncontents:\n"
        "  - chapters/chapter-01.md\n  - chapters/chapter-02.md\n  - chapters/chapter-03.md\n---\nNotes.\n"
    )
    for n, title in enumerate(["Arrival", "The Crossing", "The Storm"], start=1):
        (chapters / f"chapter-{n:02d}.md").write_text(
            f"---\ntitle: {title}\nparent: ../the-long-night.md\n---\nChapter {n} text.[^1]\n\n[^1]: Note {n}.\n"
        )
    return binder, chapters


def test_position_from_binder_order(tmp_path):
    binder, chapters = novel(tmp_path)
    ch2 = chapters / "chapter-02.md"
    pos = model.position(model.read_links(ch2, disk_read(ch2)), disk_read)
    assert model.same(pos.binder, binder)
    assert (pos.index, pos.total) == (1, 3)
    assert pos.previous.name == "chapter-01.md" and pos.next.name == "chapter-03.md"


def test_explicit_neighbors_and_aliases_win(tmp_path):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("---\nnext: b.md\nup: book.md\n---\n")
    b.write_text("---\nprev: a.md\n---\n")
    links = model.read_links(b, disk_read(b))
    assert model.position(links, disk_read).previous.name == "a.md"
    assert model.read_links(a, disk_read(a)).parents[0].name == "book.md"


def test_references_are_relative_with_forward_slashes(tmp_path):
    owner = tmp_path / "chapters" / "one.md"
    assert model.relref(owner, tmp_path / "book.md") == "../book.md"
    assert model.relref(owner, tmp_path / "chapters" / "two.md") == "two.md"


def test_add_move_remove_and_rewrite(tmp_path):
    binder, chapters = novel(tmp_path)
    text = binder.read_text()
    new = chapters / "chapter-02b.md"
    text = model.add_relation(text, binder, "contents", new, after=chapters / "chapter-02.md")
    names = [p.name for p in model.read_links(binder, text).contents]
    assert names == ["chapter-01.md", "chapter-02.md", "chapter-02b.md", "chapter-03.md"]
    text = model.move_in_contents(text, binder, new, -1)
    assert [p.name for p in model.read_links(binder, text).contents][1] == "chapter-02b.md"
    text = model.rewrite_target(text, binder, new, chapters / "interlude.md")
    assert "chapters/interlude.md" in text
    text = model.remove_relation(text, binder, "contents", chapters / "interlude.md")
    assert len(model.read_links(binder, text).contents) == 3
    assert "author: A. Writer" in text and text.endswith("Notes.\n")


def test_next_name():
    assert model.next_name(Path("chapter-02.md")) == "chapter-03.md"
    assert model.next_name(Path("part9.md")) == "part10.md"
    assert model.next_name(Path("intro.md")) == "intro-next.md"


def test_manuscript_keeps_footnotes_apart_and_titles_chapters(tmp_path):
    binder, _ = novel(tmp_path)
    text = model.manuscript_markdown(binder, disk_read)
    assert fm.read(text)["title"] == "The Long Night"
    assert "# Arrival" in text and "# The Storm" in text
    assert "[^c1-1]" in text and "[^c3-1]" in text and "[^1]" not in text
    assert "Notes." not in text
    from inkmill.export.html import render_html

    html = render_html(text)
    assert html.count('class="footnote-item"') == 3


def test_backlinks_find_documents_that_point_here(tmp_path):
    binder, chapters = novel(tmp_path)
    found = model.backlinks(binder, disk_read)
    assert {p.name for _, p in found} == {"chapter-01.md", "chapter-02.md", "chapter-03.md"}


def make_app(tmp_path, paths):
    return InkmillApp(
        paths,
        settings=Settings(restore_session=False, recovery_interval=0, plugins={"disabled": ["git_sync", "word_goal"]}),
        state=State(tmp_path / "state.json"),
        plugin_dir=PLUGINS,
    )


async def test_binder_keys_navigate_and_status_shows_chapter(tmp_path):
    binder, chapters = novel(tmp_path)
    app = make_app(tmp_path, [chapters / "chapter-02.md"])
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        right = str(app.status.query_one("#status-right").render())
        assert "Ch 2/3" in right
        await pilot.press("alt+pagedown")
        await pilot.pause(0.3)
        assert app.active_document.path.name == "chapter-03.md"
        await pilot.press("alt+up")
        await pilot.pause(0.3)
        assert app.active_document.path.name == "the-long-night.md"


async def test_navigator_opens_and_reorders(tmp_path):
    from textual.widgets import OptionList

    binder, chapters = novel(tmp_path)
    app = make_app(tmp_path, [chapters / "chapter-02.md"])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("alt+f5")
        await pilot.pause(0.3)
        option_list = app.screen.query_one(OptionList)
        assert option_list.highlighted_option.id.startswith("here|")
        await pilot.press("[")
        await pilot.pause(0.2)
        order = [p.name for p in model.read_links(binder, binder.read_text()).contents]
        assert order == ["chapter-02.md", "chapter-01.md", "chapter-03.md"]
        await pilot.press("down", "enter")
        await pilot.pause(0.3)
        assert app.active_document.path.name == "chapter-01.md"


async def test_new_next_chapter_is_inserted_in_order(tmp_path):
    binder, chapters = novel(tmp_path)
    app = make_app(tmp_path, [chapters / "chapter-02.md"])
    async with app.run_test(size=(120, 30)) as pilot:
        app.run_command("binder.new_next")
        await pilot.pause(0.3)
        from textual.widgets import Input

        app.screen.query_one(Input).value = "chapter-02b.md"
        await pilot.press("enter")
        await pilot.pause(0.4)
        new = chapters / "chapter-02b.md"
        assert new.is_file()
        assert app.active_document.path.resolve() == new.resolve()
        assert fm.read(new.read_text())["parent"] == "../the-long-night.md"
        order = [p.name for p in model.read_links(binder, binder.read_text()).contents]
        assert order == ["chapter-01.md", "chapter-02.md", "chapter-02b.md", "chapter-03.md"]


async def test_rename_in_file_manager_updates_links(tmp_path):
    binder, chapters = novel(tmp_path)
    app = make_app(tmp_path, [binder])
    async with app.run_test(size=(120, 30)) as pilot:
        old = chapters / "chapter-03.md"
        new = chapters / "the-storm.md"
        old.rename(new)
        app.file_moved(old, new)
        await pilot.pause(0.2)
        names = [p.name for p in model.read_links(binder, app.active_document.text).contents]
        assert names[-1] == "the-storm.md"
        assert not app.active_document.dirty  # it was clean, so it was saved
