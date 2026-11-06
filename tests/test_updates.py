"""Checking for a newer Inkmill and installing it."""

import sys
from pathlib import Path

import pytest

from inkmill import __main__ as cli
from inkmill import __version__, updates
from inkmill.app import InkmillApp
from inkmill.config import Settings, State
from pluginhelp import wait_for

CHANGELOG = """# Changelog

## 9.1.0 (unreleased)

- Typewriter scrolling.

## 9.0.0

- A big release.

## 0.1.0

- The first release.
"""


@pytest.fixture
def release_folder(tmp_path, monkeypatch):
    """A local stand-in for the repository's main branch, announcing 9.1.0."""
    folder = tmp_path / "repo"
    (folder / "src" / "inkmill").mkdir(parents=True)
    (folder / "src" / "inkmill" / "__init__.py").write_text('__version__ = "9.1.0"\nAPP_NAME = "Inkmill"\n')
    (folder / "CHANGELOG.md").write_text(CHANGELOG)
    monkeypatch.setenv("INKMILL_UPDATE_URL", folder.as_uri())
    return folder


def test_versions_and_notes():
    assert updates.parse_version_file('x = 1\n__version__ = "0.4.1"\n') == "0.4.1"
    with pytest.raises(updates.UpdateError):
        updates.parse_version_file("nothing here")
    assert updates.is_newer("0.4.10", "0.4.9") and not updates.is_newer("0.4.0", "0.4.0")
    notes = updates.notes_since(CHANGELOG, "0.4.0")
    assert notes.startswith("9.1.0\n") and "Typewriter" in notes and "big release" in notes
    assert "first release" not in notes and "(unreleased)" not in notes
    assert updates.notes_since(CHANGELOG, "9.1.0") == ""
    assert "Older" not in updates.notes_since("## 9.0.0\n\n- New.\n\n# Older\n\n- Old.\n", "0.4.0")


def test_fetch_release_reads_the_folder(release_folder):
    release = updates.fetch_release(updates.source_url(), current="0.4.0")
    assert release.version == "9.1.0" and release.newer_than("0.4.0") and "Typewriter" in release.notes


def test_fetch_release_reports_an_unreachable_source(tmp_path):
    with pytest.raises(updates.UpdateError, match="cannot reach"):
        updates.fetch_release((tmp_path / "missing").as_uri() + "/")


def test_due_follows_the_check_setting():
    assert updates.due({}, "daily", 1000.0)
    assert not updates.due({"checked": 1000.0}, "daily", 1000.0 + 3600)
    assert updates.due({"checked": 1000.0}, "daily", 1000.0 + updates.DAY)
    assert updates.due({"checked": 1000.0}, "startup", 1001.0)
    assert not updates.due({}, "off", 1000.0)


GIT = {"url": "https://github.com/aarondodd/inkmill.git", "vcs_info": {"vcs": "git", "commit_id": "abc"}}


def detect(tmp_path, **kw):
    base = dict(
        direct=GIT,
        prefix=str(tmp_path),
        executable="/venv/bin/python",
        windows=False,
        which=lambda name: f"/usr/bin/{name}",
        has_pip=True,
        externally_managed=False,
        dist_folder=tmp_path / "site",
        user_site=tmp_path / "user-site",
        writable=lambda p: True,
        venv=True,
    )
    base.update(kw)
    return updates.detect(**base)


def test_detect_pipx(tmp_path):
    (tmp_path / "pipx_metadata.json").write_text("{}")
    method = detect(tmp_path)
    assert method.kind == "pipx" and method.automatic
    assert method.command == ["/usr/bin/pipx", "upgrade", "inkmill"] and method.manual == ["pipx upgrade inkmill"]

    pinned = dict(GIT, vcs_info={"vcs": "git", "requested_revision": "some-branch"})
    method = detect(tmp_path, direct=pinned)
    assert method.command[1:4] == ["runpip", "inkmill", "install"]
    assert method.command[-1] == "git+https://github.com/aarondodd/inkmill.git"

    # The venv no longer records a branch, but pipx would reinstall from one.
    meta = '{"main_package": {"package_or_url": "inkmill@ git+https://github.com/aarondodd/inkmill.git@old-branch"}}'
    (tmp_path / "pipx_metadata.json").write_text(meta)
    assert detect(tmp_path).command[1] == "runpip"
    ssh = '{"main_package": {"package_or_url": "git+ssh://git@github.com/aarondodd/inkmill.git"}}'
    (tmp_path / "pipx_metadata.json").write_text(ssh)
    assert detect(tmp_path).command[1] == "upgrade"

    method = detect(tmp_path, which=lambda name: None)
    assert not method.possible and "pipx program" in method.reason and method.manual == ["pipx upgrade inkmill"]


def test_detect_pip_in_a_venv_and_the_user_site(tmp_path):
    method = detect(tmp_path)
    assert method.kind == "pip" and method.automatic and method.label == "pip (virtual environment)"
    assert method.command == ["/venv/bin/python", "-m", "pip", "install", "--upgrade", "git+https://github.com/aarondodd/inkmill.git"]

    site = tmp_path / "user-site"
    method = detect(tmp_path, venv=False, dist_folder=site, user_site=site, externally_managed=True)
    assert method.automatic and "--user" in method.command and method.label == "pip (user site-packages)"

    method = detect(tmp_path, direct={}, venv=False)
    assert method.command[-1] == "inkmill"


def test_detect_explains_what_it_cannot_do(tmp_path):
    managed = detect(tmp_path, venv=False, externally_managed=True)
    assert not managed.possible and "package manager" in managed.reason and managed.manual
    locked = detect(tmp_path, writable=lambda p: False)
    assert not locked.possible and "permission" in locked.reason
    nopip = detect(tmp_path, has_pip=False)
    assert not nopip.possible and "pip is not available" in nopip.reason
    source = detect(tmp_path, direct={"url": (tmp_path / "src").as_uri(), "dir_info": {"editable": True}})
    assert source.kind == "source" and not source.possible and "git pull" in source.manual


def test_detect_defers_on_windows(tmp_path):
    method = detect(tmp_path, windows=True, executable=r"C:\Program Files\Python\python.exe")
    assert method.deferred and not method.automatic and "locked" in method.reason
    assert method.manual[0].startswith('"C:\\Program Files\\Python\\python.exe" -m pip')
    script = updates.deferred_script(method, 4242)
    assert script.startswith("Wait-Process -Id 4242")
    assert "& 'C:\\Program Files\\Python\\python.exe' '-m' 'pip'" in script
    assert updates.powershell_quote("it's") == "'it''s'"


def test_install_runs_the_command_and_reports_failure():
    ok = updates.Method("pip", "pip", command=[sys.executable, "-c", "print('installed')"])
    assert updates.install(ok) == "installed"
    bad = updates.Method("pip", "pip", command=[sys.executable, "-c", "import sys; print('no network'); sys.exit(3)"])
    with pytest.raises(updates.UpdateError, match="exit 3") as info:
        updates.install(bad)
    assert "no network" in str(info.value)
    with pytest.raises(updates.UpdateError):
        updates.install(updates.Method("source", "a source folder", reason="use git"))


def test_installed_version_asks_a_fresh_interpreter():
    assert updates.installed_version() == __import__("importlib.metadata").metadata.version("inkmill")


def test_describe(tmp_path):
    method = detect(tmp_path, has_pip=False)
    text = updates.describe(updates.Release("9.1.0", "9.1.0\n\n- New."), method, current="0.4.0")
    assert "Inkmill 9.1.0 is available. You have 0.4.0." in text and "- New." in text
    assert "To update, run:" in text and method.manual[0] in text
    assert updates.describe(updates.Release("0.4.0"), method, current="0.4.0") == "Inkmill 0.4.0 is the newest version."


def test_command_line_check_and_update(release_folder, monkeypatch, capsys):
    monkeypatch.setattr(updates, "detect", lambda: updates.Method("pip", "pip", command=["x"], automatic=True))
    assert cli.main(["--check-update"]) == 0
    assert "Inkmill 9.1.0 is available" in capsys.readouterr().out

    monkeypatch.setattr(updates, "install", lambda method: "ok")
    monkeypatch.setattr(updates, "installed_version", lambda executable=None: "9.1.0")
    assert cli.main(["--update"]) == 0
    assert "Inkmill 9.1.0 is installed." in capsys.readouterr().out

    monkeypatch.setattr(updates, "installed_version", lambda executable=None: __version__)
    assert cli.main(["--update"]) == 1
    assert "still installed" in capsys.readouterr().err

    manual = updates.Method("pip", "pip", manual=["pip install --upgrade inkmill"], reason="No pip here.")
    monkeypatch.setattr(updates, "detect", lambda: manual)
    assert cli.main(["--update"]) == 1
    assert "pip install --upgrade inkmill" in capsys.readouterr().out


def make_app(tmp_path, **updates_table):
    doc = tmp_path / "d.md"
    doc.write_text("Text.\n")
    settings = Settings(restore_session=False, recovery_interval=0, updates=updates_table)
    return InkmillApp([doc], settings=settings, state=State(tmp_path / "state.json"), load_plugins=False)


async def test_check_for_updates_installs_and_offers_a_restart(tmp_path, release_folder, monkeypatch):
    calls = []
    method = updates.Method("pip", "pip (virtual environment)", command=["x"], manual=["pip install"], automatic=True)
    monkeypatch.setattr(updates, "detect", lambda: method)
    monkeypatch.setattr(updates, "install", lambda m: calls.append(m) or "ok")
    monkeypatch.setattr(updates, "installed_version", lambda executable=None: "9.1.0")
    app = make_app(tmp_path, check="off")
    async with app.run_test(size=(100, 40)) as pilot:
        app.run_command("help.updates")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "TextDialog")
        assert "Inkmill 9.1.0 is available" in str(app.screen.body)
        await pilot.press("i")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog")
        assert calls == [method] and app.update_installed == "9.1.0"
        await pilot.press("r")
        assert await wait_for(pilot, lambda: app.after_exit == "restart" and app._exit)
    assert app.state.data["updates"]["latest"] == "9.1.0"


async def test_check_for_updates_shows_the_command_when_it_cannot_install(tmp_path, release_folder, monkeypatch):
    method = updates.Method("pip", "pip", manual=["python -m pip install --upgrade inkmill"], reason="No pip here.")
    monkeypatch.setattr(updates, "detect", lambda: method)
    app = make_app(tmp_path, check="off")
    async with app.run_test(size=(100, 40)) as pilot:
        app.run_command("help.updates")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "TextDialog")
        body = str(app.screen.body)
        assert "No pip here." in body and "python -m pip install --upgrade inkmill" in body
        copied = []
        monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
        await pilot.press("c")
        assert await wait_for(pilot, lambda: copied == ["python -m pip install --upgrade inkmill"])


async def test_windows_update_waits_for_quit(tmp_path, release_folder, monkeypatch):
    method = updates.Method("pipx", "pipx", command=["pipx", "upgrade", "inkmill"], deferred=True, reason="locked")
    monkeypatch.setattr(updates, "detect", lambda: method)
    started = []
    monkeypatch.setattr(updates, "start_deferred", lambda m, pid=None: started.append(m))
    app = make_app(tmp_path, check="off")
    async with app.run_test(size=(100, 40)) as pilot:
        app.run_command("help.updates")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "TextDialog")
        await pilot.press("u")
        assert await wait_for(pilot, lambda: app._exit)
    assert app.pending_update is method
    cli.after_exit(app, load_plugins=False)
    assert started == [method]


async def test_startup_check_notifies_once_a_day(tmp_path, release_folder, monkeypatch):
    monkeypatch.setattr(updates, "detect", lambda: updates.Method("pip", "pip", command=["x"], automatic=True))
    app = make_app(tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        assert await wait_for(pilot, lambda: any("9.1.0 is available" in str(n.message) for n in app._notifications))
    checked = app.state.data["updates"]["checked"]
    app2 = InkmillApp(settings=Settings(restore_session=False, recovery_interval=0), state=State(tmp_path / "state.json"), load_plugins=False)
    async with app2.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.3)
        assert not any("available" in str(n.message) for n in app2._notifications)
    assert app2.state.data["updates"]["checked"] == checked


async def test_startup_auto_install(tmp_path, release_folder, monkeypatch):
    monkeypatch.setattr(updates, "detect", lambda: updates.Method("pip", "pip", command=["x"], automatic=True))
    monkeypatch.setattr(updates, "install", lambda m: "ok")
    monkeypatch.setattr(updates, "installed_version", lambda executable=None: "9.1.0")
    app = make_app(tmp_path, auto_install=True)
    async with app.run_test(size=(100, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.update_installed == "9.1.0")
        assert await wait_for(pilot, lambda: any("is installed" in str(n.message) for n in app._notifications))


def test_restart_after_update_starts_a_new_process(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli.os, "execv", lambda exe, argv: seen.append(argv))

    class Done:
        pending_update = None
        after_exit = "restart"
        state = State(tmp_path / "s.json")

    Done.state.session = [str(Path("/x/a.md"))]
    cli.after_exit(Done, load_plugins=True)
    assert seen == [[sys.executable, "-m", "inkmill", str(Path("/x/a.md"))]]
