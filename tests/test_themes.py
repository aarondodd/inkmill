from pathlib import Path

import pytest
from textual.app import App

from inkmill.app import InkmillApp
from inkmill.config import Settings, State, config_dir
from inkmill.themes import UI_KEYS, derive_variables, make_theme

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"


def test_textual_themes_get_their_own_ui_colors():
    nord = App().get_theme("nord")
    v = derive_variables(nord)
    assert set(v) == {f"im-{k}" for k in UI_KEYS}
    assert v["im-menu-bg"].lower() == "#434c5e"
    assert v["im-dialog-border"].lower() == "#88c0d0"
    assert v["im-cursor-fg"].lower() == "#2e3440"


def test_make_theme_derives_and_validates():
    theme = make_theme("t", dark=True, background="#10202a", foreground="#d8e2e6", primary="#4fb3bf", menu_key="#f2c14e")
    assert theme.variables["im-menu-key"] == "#f2c14e"
    assert theme.variables["im-select-bg"].lower() == "#4fb3bf"
    with pytest.raises(ValueError, match="unknown theme keys"):
        make_theme("t", dark=True, background="#000", foreground="#fff", primary="#0ff", menu_colour="#fff")
    with pytest.raises(ValueError):
        make_theme("t", dark=True, background="not-a-color", foreground="#fff", primary="#0ff")


def make_app(tmp_path):
    return InkmillApp(
        settings=Settings(restore_session=False, recovery_interval=0, plugins={"disabled": ["binder", "git_sync", "word_goal"]}),
        state=State(tmp_path / "state.json"),
        plugin_dir=PLUGINS,
    )


def test_bundled_themes_all_load(tmp_path):
    app = make_app(tmp_path)
    assert not [p for p in app.plugin_info if p.error]
    bundled = sorted(p.stem for p in (PLUGINS / "themes" / "themes").glob("*.toml"))
    assert len(bundled) == 10
    for name in bundled:
        assert name in app.available_themes


def test_bad_user_theme_is_reported_not_loaded(tmp_path):
    folder = config_dir() / "themes"
    folder.mkdir(parents=True)
    (folder / "broken.toml").write_text('name = "broken"\ndark = true\nbackground = "#000"\n')
    (folder / "mine.toml").write_text('name = "mine"\ndark = false\nbackground = "#fafafa"\nforeground = "#111111"\nprimary = "#cc3300"\n')
    app = make_app(tmp_path)
    assert "mine" in app.available_themes
    assert "broken" not in app.available_themes


async def test_gallery_previews_live_and_cancel_restores(tmp_path):
    from textual.widgets import OptionList

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        assert app.theme == "wordperfect"
        app.run_command("themes.gallery")
        await pilot.pause(0.3)
        await pilot.press("down")
        await pilot.pause(0.2)
        previewed = app.theme
        assert previewed != "wordperfect"
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert app.theme == "wordperfect"
        app.run_command("themes.gallery")
        await pilot.pause(0.3)
        option_list = app.screen.query_one(OptionList)
        index = next(i for i, o in enumerate(option_list._options) if o.id == "turbo")
        option_list.highlighted = index
        await pilot.pause(0.2)
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert app.theme == "turbo" and app.settings.theme == "turbo"
        assert app.current_theme.variables["im-menu-hl-bg"] == "#00aa00"


async def test_new_theme_file_applies_on_save(tmp_path):
    from textual.widgets import Input

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        app.run_command("themes.new")
        await pilot.pause(0.3)
        app.screen.query_one(Input).value = "harbor"
        await pilot.press("enter")
        await pilot.pause(0.4)
        path = config_dir() / "themes" / "harbor.toml"
        assert path.is_file()
        assert app.active_document.path == path
        assert app.theme == "harbor"
        doc = app.active_document
        app.replace_document_text(doc, doc.text.replace('background = "#0000aa"', 'background = "#123456"'))
        await pilot.press("ctrl+s")
        await pilot.pause(0.3)
        assert app.current_theme.background.lower() == "#123456"
