from inkmill.app import InkmillApp
from inkmill.config import Settings, State

PLUGIN = '''
from inkmill.export import Exporter

def register(api):
    @api.command("demo.shout", "Shout", "ctrl+u", menu="format")
    def shout(app):
        app.active_editor.insert("HEY")

    @api.command("demo.other", "Other", menu="demo")
    def other(app):
        pass

    api.register_exporter(Exporter("txt", "Plain text", ".txt", lambda doc, settings: doc.text))
    api.settings["loaded"] = True
'''


def make_app(tmp_path, plugin_dir):
    return InkmillApp(settings=Settings(), state=State(tmp_path / "s.json"), plugin_dir=plugin_dir)


def test_plugins_register_commands_menus_and_exporters(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "demo.py").write_text(PLUGIN)
    (plugin_dir / "broken.py").write_text("raise RuntimeError('nope')\n")
    (plugin_dir / "_private.py").write_text("raise RuntimeError('skipped')\n")
    app = make_app(tmp_path, plugin_dir)
    infos = {p.name: p for p in app.plugin_info}
    assert infos["demo"].error is None
    assert "RuntimeError" in infos["broken"].error
    assert "_private" not in infos
    assert "demo.shout" in app.commands
    assert any(getattr(i, "command", None) == "demo.shout" for i in app.menus.get("format").items)
    menu_ids = [m.id for m in app.menus]
    assert menu_ids.index("demo") == menu_ids.index("help") - 1
    assert app.exporters.get("txt") is not None
    assert app.settings.plugins["demo"]["loaded"] is True


def test_disabled_plugins_are_skipped(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "demo.py").write_text(PLUGIN)
    settings = Settings(plugins={"disabled": ["demo"]})
    app = InkmillApp(settings=settings, state=State(tmp_path / "s.json"), plugin_dir=plugin_dir)
    assert "demo.shout" not in app.commands


async def test_plugin_command_runs_from_its_key(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "demo.py").write_text(PLUGIN)
    app = make_app(tmp_path, plugin_dir)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+u")
        await pilot.pause()
        assert app.active_document.text == "HEY"


def test_repository_plugins_load(tmp_path):
    from pathlib import Path

    plugins = Path(__file__).parent.parent / "plugins"
    app = make_app(tmp_path, plugins)
    assert all(p.error is None for p in app.plugin_info), [p.error for p in app.plugin_info]
    assert all(p.skipped is None for p in app.plugin_info), [(p.name, p.skipped) for p in app.plugin_info]
    for menu in ("tools", "git", "review", "binder", "ai"):
        assert app.menus.get(menu) is not None, menu
    assert {p.name: p.version for p in app.plugin_info}["binder"] == "1.1.0"
    assert app.commands.key_conflicts() == {}


def test_example_plugin_loads(tmp_path):
    from pathlib import Path

    examples = Path(__file__).parent.parent / "examples" / "plugins"
    app = make_app(tmp_path, examples)
    assert all(p.error is None for p in app.plugin_info), [p.error for p in app.plugin_info]
    assert "word_goal.progress" in app.commands


def test_menu_accelerators_are_unique(tmp_path):
    from pathlib import Path

    from inkmill.menus import MenuItem, split_accelerator

    app = make_app(tmp_path, Path(__file__).parent.parent / "plugins")
    letters = [m.accelerator for m in app.menus]
    assert len(letters) == len(set(letters)), letters
    for menu in app.menus:
        seen = {}
        for item in menu.items:
            if not isinstance(item, MenuItem):
                continue
            label = item.label or app.commands.get(item.command).label
            letter = split_accelerator(label)[1]
            if letter:
                assert letter.lower() not in seen, (menu.id, label, seen.get(letter.lower()))
                seen[letter.lower()] = label


async def test_every_menu_is_reachable_on_a_phone_width_screen(tmp_path):
    from pathlib import Path

    from inkmill.menus import split_accelerator
    from inkmill.widgets.menubar import MenuDropdown, MenuScreen, MenuStrip

    app = make_app(tmp_path, Path(__file__).parent.parent / "plugins")
    async with app.run_test(size=(48, 24)) as pilot:
        await pilot.press("escape")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, MenuScreen)
        for i, menu in enumerate(app.menus):
            screen._show(i)
            await pilot.pause()
            strip = screen.query_one(MenuStrip)
            assert split_accelerator(menu.label)[0] in strip.render().plain, menu.label
            dropdown = screen.query_one(MenuDropdown)
            assert dropdown.region.right <= 48, (menu.label, dropdown.region)
