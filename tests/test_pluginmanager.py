import json
import subprocess
import sys
from pathlib import Path

import pytest

from inkmill.app import InkmillApp
from inkmill.config import Settings, State
from inkmill.pluginmanager import (
    PluginSourceError,
    Source,
    build_rows,
    fetch_index,
    install,
    installed_plugins,
    previous_version,
    remove,
    rollback,
)
from inkmill.plugins import is_compatible, load_plugins

ROOT = Path(__file__).resolve().parent.parent


def write_source(tmp_path, version="1.0.0", requires=">=0.2", body="def register(api):\n    api.settings['ok'] = True\n"):
    """A local plugin source holding one plugin, with a correct index."""
    src = tmp_path / "src"
    plugin = src / "plugins" / "hello"
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "plugin.toml").write_text(f'id = "hello"\nname = "Hello"\nversion = "{version}"\nrequires_inkmill = "{requires}"\n')
    (plugin / "__init__.py").write_text(body)
    (plugin / "README.md").write_text("# Hello\n")
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_plugin_index

        index = build_plugin_index.build(src / "plugins")
    finally:
        sys.path.pop(0)
    (src / "plugins" / "index.json").write_text(json.dumps(index))
    return src


def test_compatibility_checks():
    assert is_compatible(">=0.2", "0.2.0")
    assert not is_compatible(">=0.3", "0.2.0")
    assert is_compatible(">=0.2,<1", "0.9.1")
    assert is_compatible("", "0.1.0")
    assert not is_compatible("not a specifier", "0.2.0")


def test_install_update_rollback_remove(tmp_path):
    src = write_source(tmp_path)
    dest = tmp_path / "plugins"
    source = Source("local", str(src))
    [entry] = fetch_index(source)
    path = install(entry, source, dest)
    assert (path / "__init__.py").is_file()
    inst = installed_plugins(dest)["hello"]
    assert inst.managed and inst.version == "1.0.0"

    src = write_source(tmp_path, version="1.1.0", body="def register(api):\n    api.settings['v'] = 2\n")
    [entry] = fetch_index(source)
    rows = build_rows([entry], installed_plugins(dest), directory=dest)
    assert rows[0].status == "update" and rows[0].has_update
    install(entry, source, dest)
    assert installed_plugins(dest)["hello"].version == "1.1.0"
    assert previous_version("hello", dest) == "1.0.0"
    rollback("hello", dest)
    assert installed_plugins(dest)["hello"].version == "1.0.0"
    remove("hello", dest)
    assert "hello" not in installed_plugins(dest)


def test_hash_mismatch_leaves_nothing_behind(tmp_path):
    src = write_source(tmp_path)
    (src / "plugins" / "hello" / "__init__.py").write_text("tampered = True\n")
    dest = tmp_path / "plugins"
    source = Source("local", str(src))
    [entry] = fetch_index(source)
    with pytest.raises(PluginSourceError, match="does not match"):
        install(entry, source, dest)
    assert not (dest / "hello").exists()
    assert not any(p.name.startswith(".staging") for p in dest.iterdir())


def test_unsafe_names_and_incompatible_plugins_are_refused(tmp_path):
    src = write_source(tmp_path, requires=">=99")
    source = Source("local", str(src))
    [entry] = fetch_index(source)
    assert not entry.compatible
    with pytest.raises(PluginSourceError, match="needs Inkmill"):
        install(entry, source, tmp_path / "plugins")
    entry.manifest.requires_inkmill = ""
    entry.files = {"../escape.py": "0" * 64}
    with pytest.raises(PluginSourceError, match="unsafe"):
        install(entry, source, tmp_path / "plugins")
    rows = build_rows(fetch_index(source), {})
    assert rows[0].status == "incompatible"


def test_loader_skips_plugins_for_newer_inkmill(tmp_path):
    folder = tmp_path / "plugins" / "future"
    folder.mkdir(parents=True)
    (folder / "plugin.toml").write_text('id = "future"\nname = "Future"\nversion = "1.0"\nrequires_inkmill = ">=99"\n')
    (folder / "__init__.py").write_text("raise RuntimeError('should not load')\n")
    app = InkmillApp(settings=Settings(), state=State(tmp_path / "s.json"), load_plugins=False)
    [info] = load_plugins(app, tmp_path / "plugins")
    assert info.skipped == "needs Inkmill 99 or newer"
    assert info.error is None


def test_missing_local_source_reports_clearly(tmp_path):
    with pytest.raises(PluginSourceError, match="no plugins/index.json"):
        fetch_index(Source("local", str(tmp_path / "nowhere")))
    with pytest.raises(PluginSourceError, match="no local folder"):
        Source("local", "").read()


def test_repository_index_is_current():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_plugin_index.py"), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_every_repository_plugin_installs_from_a_local_clone(tmp_path):
    source = Source("local", str(ROOT))
    entries = fetch_index(source)
    assert {e.id for e in entries} == {
        "ai", "binder", "comments", "git_sync", "links", "outline", "pandoc", "progress", "prose",
        "snapshots", "spelling", "templates", "themes",
    }
    dest = tmp_path / "plugins"
    for entry in entries:
        install(entry, source, dest)
    app = InkmillApp(settings=Settings(), state=State(tmp_path / "s.json"), plugin_dir=dest)
    errors = {p.name: p.error for p in app.plugin_info if p.error}
    assert not errors, errors
    for command in ("binder.navigator", "git_sync.commit", "progress.show", "spelling.check", "ai.ask"):
        assert command in app.commands
    # Every plugin loaded together: no two commands may share a key.
    assert app.commands.key_conflicts() == {}


async def test_manager_screen_installs_and_restarts(tmp_path):
    from inkmill.screens.plugins import PluginManagerScreen

    src = write_source(tmp_path)
    dest = tmp_path / "plugins"
    settings = Settings(restore_session=False, recovery_interval=0, plugin_manager={"source": "local", "local_path": str(src)})
    app = InkmillApp(settings=settings, state=State(tmp_path / "s.json"), plugin_dir=dest)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press(*"draft")
        app.run_command("view.plugins")
        await pilot.pause(0.5)
        screen = app.screen
        assert isinstance(screen, PluginManagerScreen)
        await pilot.pause(0.3)
        assert [r.id for r in screen.rows] == ["hello"]
        assert screen.rows[0].status == "available"
        await pilot.press("1")
        await pilot.pause(0.3)
        await pilot.press("y")
        await pilot.pause(0.5)
        assert (dest / "hello" / "__init__.py").is_file()
        assert screen.pending_restart
        await pilot.press("r")
        await pilot.pause(0.3)
    handoff = app.restart_handoff
    assert handoff is not None
    assert handoff.docs[0]["text"] == "draft"


def test_changed_files_need_a_version_bump():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_plugin_index
    finally:
        sys.path.pop(0)
    new = {"plugins": [{"id": "a", "version": "1.0.0", "files": {"x.py": "2"}}]}
    same_version = {"plugins": [{"id": "a", "version": "1.0.0", "files": {"x.py": "1"}}]}
    bumped = {"plugins": [{"id": "a", "version": "0.9.0", "files": {"x.py": "1"}}]}
    assert build_plugin_index.unbumped(new, same_version) == ["a: files changed but version is still 1.0.0"]
    assert build_plugin_index.unbumped(new, bumped) == []
