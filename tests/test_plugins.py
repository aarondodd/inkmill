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
    assert "word_goal.progress" in app.commands
    assert app.menus.get("tools") is not None
    assert app.menus.get("git") is not None
    assert {p.name: p.version for p in app.plugin_info}["binder"] == "1.0.0"
