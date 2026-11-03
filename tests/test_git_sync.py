import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from inkmill.app import InkmillApp
from inkmill.config import Settings, State

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def load_gitcmd():
    spec = importlib.util.spec_from_file_location("git_sync_gitcmd_under_test", PLUGINS / "git_sync" / "gitcmd.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gitcmd = load_gitcmd()


def sh(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def setup_repos(tmp_path):
    """A bare remote, a working clone with one committed document, and a second clone."""
    remote = tmp_path / "remote.git"
    sh("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    work = tmp_path / "work"
    sh("clone", str(remote), str(work), cwd=tmp_path)
    sh("config", "user.name", "Test Writer", cwd=work)
    sh("config", "user.email", "writer@example.com", cwd=work)
    sh("symbolic-ref", "HEAD", "refs/heads/main", cwd=work)
    (work / "chapter.md").write_text("First line.\n")
    (work / "notes.md").write_text("Notes.\n")
    sh("add", "-A", cwd=work)
    sh("commit", "-m", "Start", cwd=work)
    sh("push", "-u", "origin", "main", cwd=work)
    other = tmp_path / "other"
    sh("clone", "-b", "main", str(remote), str(other), cwd=tmp_path)
    sh("config", "user.name", "Other", cwd=other)
    sh("config", "user.email", "other@example.com", cwd=other)
    return remote, work, other


def test_advice_classification():
    assert gitcmd.kind("fatal: could not read Username for 'https://github.com': terminal prompts disabled") == "auth"
    assert gitcmd.kind("git@github.com: Permission denied (publickey).") == "publickey"
    assert gitcmd.kind("fatal: detected dubious ownership in repository at '/sdcard/x'") == "ownership"
    assert gitcmd.kind("fatal: Not possible to fast-forward, aborting.") == "diverged"
    assert gitcmd.kind(" ! [rejected]        main -> main (fetch first)") == "rejected"
    assert gitcmd.kind("Author identity unknown\n*** Please tell me who you are.") == "identity"
    assert "credential" in gitcmd.advice("fatal: Authentication failed for 'https://x/'").lower()


def test_status_and_commit_only_named_paths(tmp_path):
    _, work, _ = setup_repos(tmp_path)
    (work / "chapter.md").write_text("First line.\nSecond.\n")
    (work / "notes.md").write_text("Changed notes.\n")
    (work / "new file.md").write_text("New.\n")
    st = gitcmd.status(work)
    assert st.branch == "main" and st.upstream == "origin/main"
    assert {p for _, p in st.changes} == {"chapter.md", "notes.md", "new file.md"}
    result = gitcmd.commit(work, "Chapter edits", [work / "chapter.md"])
    assert result.ok, result.text
    st = gitcmd.status(work)
    assert {p for _, p in st.changes} == {"notes.md", "new file.md"}
    assert st.ahead == 1
    assert gitcmd.repo_root(work / "chapter.md").resolve() == work.resolve()
    assert gitcmd.repo_root(tmp_path / "chapter.md") is None


def make_app(tmp_path, paths):
    return InkmillApp(
        paths,
        settings=Settings(restore_session=False, recovery_interval=0, plugins={"disabled": ["binder", "word_goal"]}),
        state=State(tmp_path / "state.json"),
        plugin_dir=PLUGINS,
    )


async def wait_for(pilot, predicate, timeout=10.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        await pilot.pause(0.1)
    return predicate()


async def test_commit_dialog_commits_and_pushes(tmp_path):
    _, work, _ = setup_repos(tmp_path)
    app = make_app(tmp_path, [work / "chapter.md"])
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("end", *" More.")
        await pilot.press("ctrl+f12")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "CommitDialog")
        from textual.widgets import Checkbox, Input

        app.screen.query_one(Input).value = "Day one"
        app.screen.query_one(Checkbox).value = True
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: gitcmd.status(work).ahead == 0 and not gitcmd.status(work).changes)
    log = subprocess.run(["git", "log", "-1", "--format=%s", "origin/main"], cwd=work, capture_output=True, text=True)
    assert log.stdout.strip() == "Day one"
    notes = gitcmd.status(work)
    assert not notes.changes


async def test_pull_reloads_open_documents(tmp_path):
    _, work, other = setup_repos(tmp_path)
    (other / "chapter.md").write_text("Edited elsewhere.\n")
    sh("commit", "-am", "Remote edit", cwd=other)
    sh("push", cwd=other)
    app = make_app(tmp_path, [work / "chapter.md"])
    async with app.run_test(size=(120, 30)) as pilot:
        app.run_command("git_sync.pull")
        assert await wait_for(pilot, lambda: app.active_document.text == "Edited elsewhere.\n")
        assert not app.active_document.dirty


async def test_pull_refuses_without_saving(tmp_path):
    from inkmill.screens.dialogs import ConfirmDialog

    _, work, _ = setup_repos(tmp_path)
    app = make_app(tmp_path, [work / "chapter.md"])
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press(*"unsaved ")
        app.run_command("git_sync.pull")
        assert await wait_for(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press("c")
        await pilot.pause(0.2)
        assert app.active_document.dirty
