"""Progress, Snapshots, Prose Check, Comments, Templates and Links."""

from pathlib import Path

from textual.widgets import Input, OptionList

from inkmill.config import config_dir
from pluginhelp import app_with, load_module, wait_for

critic = load_module("comments", "critic")
rules = load_module("prose", "rules")
store_mod = load_module("snapshots", "store")
log_mod = load_module("progress", "log")
links_model = load_module("links", "model")
templates_mod = load_module("templates", "__init__")


# -- Progress ------------------------------------------------------------------

def test_writing_log_counts_net_words_and_streaks(tmp_path):
    log = log_mod.WritingLog(tmp_path / "p.json")
    log.see("a", 100)
    log.see("a", 160)
    log.see("b", 10)
    log.see("b", 5)
    assert log.words() == 55
    log.save()
    again = log_mod.WritingLog(tmp_path / "p.json")
    assert again.words() == 55
    assert again.streak(50) == 1
    assert "a day" in log_mod.pace(1000, 5000, "2999-01-01")
    assert log_mod.pace(6000, 5000, "2999-01-01") == "target reached"


async def test_progress_status_and_goal(tmp_path):
    doc = tmp_path / "d.md"
    doc.write_text("one two three\n")
    app = app_with(tmp_path, "progress", paths=[doc], plugins={"progress": {"daily_goal": 5}})
    async with app.run_test() as pilot:
        await pilot.press("end", *" four five six")
        assert await wait_for(pilot, lambda: "Today 3/5" in str(app.status.query_one("#status-right").render()))
        await pilot.press(*" seven eight")
        assert await wait_for(pilot, lambda: "Today 5/5" in str(app.status.query_one("#status-right").render()))


# -- Snapshots ------------------------------------------------------------------

def test_snapshot_store_and_compare(tmp_path):
    doc = tmp_path / "ch.md"
    doc.write_text("x")
    store = store_mod.Store(doc, tmp_path / "snaps")
    store.take("The cat sat on the mat.\n\nEnd.\n", "first")
    store.take("The dog sat on the rug.\n\nEnd.\n")
    snaps = store.list()
    assert [s.name for s in snaps] == ["", "first"]
    text = store_mod.compare(snaps[1].read(), snaps[0].read())
    plain = text.plain
    assert "catdog" in plain.replace(" ", "") or ("cat" in plain and "dog" in plain)
    struck = [span for span in text.spans if "strike" in str(span.style)]
    assert struck
    store.delete(snaps[1])
    assert len(store.list()) == 1
    beside = store_mod.Store(doc, tmp_path / "unused", beside=True)
    assert beside.folder == doc.parent / ".snapshots" / "ch.md"


async def test_snapshot_restore(tmp_path):
    doc = tmp_path / "d.md"
    doc.write_text("Version one.\n")
    app = app_with(tmp_path, "snapshots", paths=[doc])
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.press("ctrl+f5")
        await pilot.pause(0.2)
        app.screen.query_one(Input).value = "v1"
        await pilot.press("enter")
        await pilot.pause(0.3)
        app.replace_document_text(app.active_document, "Version two.\n")
        app.run_command("snapshots.list")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "SnapshotList")
        await pilot.press("r")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog")
        await pilot.press("y")
        assert await wait_for(pilot, lambda: app.active_document.text == "Version one.\n")


# -- Prose Check -----------------------------------------------------------------

def test_prose_rules():
    text = "# The Title Was Written\n\nThe ball was thrown. It was very good, in order to win. He ran. He fell. He hid.\n"
    found = {f.rule for f in rules.check(text)}
    assert {"passive", "filler", "wordy", "opener", "starts"} <= found
    assert not any(f.start < text.index("\n") for f in rules.check(text))  # headings are skipped
    stats = rules.readability(text)
    assert stats["sentences"] == 5 and stats["words"] > 10


async def test_prose_panel_lists_and_selects(tmp_path):
    doc = tmp_path / "d.md"
    doc.write_text("The ball was thrown by him.\n")
    app = app_with(tmp_path, "prose", paths=[doc])
    async with app.run_test(size=(120, 30)) as pilot:
        app.run_command("prose.check")
        assert await wait_for(pilot, lambda: app.panel.visible and app.panel.query_one(OptionList).option_count > 1)
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert app.active_editor.selected_text == "was thrown"
        assert app.active_editor.decorations("prose")


# -- Comments --------------------------------------------------------------------

def test_criticmarkup_resolve_and_html():
    text = "A {++new ++}{--old --}word, {~~red~>blue~~} sky {==here==}{>>check this<<}."
    assert critic.resolve(text, accept=True) == "A new word, blue sky here."
    assert critic.resolve(text, accept=False) == "A old word, red sky here."
    html = critic.to_html(text)
    assert "<ins" in html and "<del" in html and "critic-comment" in html
    assert [m.kind for m in critic.marks(text)] == ["add", "delete", "replace", "highlight"]


async def test_comment_review_accepts(tmp_path):
    doc = tmp_path / "d.md"
    doc.write_text("Keep {--this--}that.\n")
    app = app_with(tmp_path, "comments", paths=[doc])
    async with app.run_test(size=(120, 30)) as pilot:
        assert await wait_for(pilot, lambda: app.active_editor.decorations("comments"))
        app.run_command("comments.review")
        assert await wait_for(pilot, lambda: app.panel.visible)
        await pilot.press("a")
        assert await wait_for(pilot, lambda: app.active_document.text == "Keep that.\n")


def test_comment_export_modes(tmp_path):
    from inkmill.export.markdown import clear_extensions, render

    app = app_with(tmp_path, "comments")
    assert "<del" in render("Old {--gone--} text").body
    app.settings.plugins["comments"]["export"] = "final"
    from inkmill.export.markdown import build_parser

    build_parser.cache_clear()
    assert "gone" not in render("Old {--gone--} text").body
    clear_extensions()


# -- Templates -------------------------------------------------------------------

def test_template_fill():
    text, cursor = templates_mod.fill("---\ntemplate: X\ntitle: \"{{title}}\"\n---\n# {{title}}\n\n{{cursor}}\n{{unknown}}", {"title": "Hi"})
    assert "template:" not in text
    assert "# Hi" in text and "{{unknown}}" in text
    assert text[cursor:].startswith("\n{{unknown}}")


async def test_new_from_template_and_journal(tmp_path):
    app = app_with(tmp_path, "templates", plugins={"templates": {"journal_dir": str(tmp_path / "journal")}})
    async with app.run_test(size=(110, 30)) as pilot:
        app.run_command("templates.new")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ChoiceDialog")
        option_list = app.screen.query_one(OptionList)
        option_list.highlighted = next(i for i, o in enumerate(option_list._options) if o.id == "character")
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "InputDialog")
        app.screen.query_one(Input).value = "Mara Venn"
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: "# Mara Venn" in app.active_document.text)
        app.run_command("templates.journal")
        assert await wait_for(pilot, lambda: app.active_document.path is not None and app.active_document.path.parent == tmp_path / "journal")
        assert "\n## " in app.active_document.text


# -- Links -----------------------------------------------------------------------

def test_link_parsing_and_index(tmp_path):
    (tmp_path / ".git").mkdir()
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "Mara Venn.md").write_text("---\ntitle: Captain Venn\n---\nx")
    (tmp_path / "ch1.md").write_text("See [[Mara Venn]].")
    idx = links_model.Index(links_model.project_root(tmp_path / "ch1.md")).build()
    assert idx.find("mara venn").name == "Mara Venn.md"
    assert idx.find("Captain Venn").name == "Mara Venn.md"
    link = links_model.link_at("See [[Mara Venn#Arc|her]] now", 8)
    assert (link.kind, link.target, link.anchor, link.label) == ("wiki", "Mara Venn", "Arc", "her")
    assert links_model.link_at("a [x](other.md#top) b", 4).target == "other.md"
    assert links_model.link_at("go https://x.org/y. now", 6).target == "https://x.org/y"


async def test_follow_wikilink_and_back(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "Mara.md").write_text("# Mara\n\n## Arc\nGrows.\n")
    ch = tmp_path / "ch1.md"
    ch.write_text("Meet [[Mara#Arc]] today.\n")
    app = app_with(tmp_path, "links", paths=[ch])
    async with app.run_test(size=(110, 30)) as pilot:
        app.active_editor.cursor_location = (0, 8)
        await pilot.press("alt+l")
        assert await wait_for(pilot, lambda: app.active_document.path.name == "Mara.md")
        assert app.active_editor.cursor_location[0] == 2
        await pilot.press("alt+left")
        assert await wait_for(pilot, lambda: app.active_document.path.name == "ch1.md")


def test_wikilinks_render_as_links(tmp_path):
    from inkmill.export.markdown import clear_extensions, render

    app_with(tmp_path, "links")
    body = render("See [[Mara Venn|her]] and `[[code]]`.").body
    assert '<a href="Mara%20Venn.html" class="wikilink">her</a>' in body
    assert "[[code]]" in body
    clear_extensions()
