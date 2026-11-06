"""The AI Assistant's Claude Code provider, against a fake claude program."""

import json
import sys
import threading
from pathlib import Path

import pytest

from pluginhelp import app_with, load_module, wait_for

cc = load_module("ai", "claudecode")
FAKE = Path(__file__).with_name("fake_claude.py")


@pytest.fixture
def fake(tmp_path, monkeypatch):
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))

    def calls():
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    return [sys.executable, str(FAKE)], calls


def command_setting() -> str:
    return f'"{sys.executable}" "{FAKE}"'


def test_build_args_for_a_new_and_a_resumed_conversation(tmp_path):
    args = cc.build_args(["claude"], system="S", model="sonnet", session="abc", add_dirs=(tmp_path,))
    assert args[:2] == ["claude", "-p"]
    assert args[args.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in args
    assert args[args.index("--tools") + 1] == "Read,Grep,Glob"
    assert args[args.index("--allowedTools") + 1] == "Read,Grep,Glob"
    assert args[args.index("--add-dir") + 1] == str(tmp_path)
    assert args[args.index("--session-id") + 1] == "abc" and "--resume" not in args
    resumed = cc.build_args(["claude"], system="S", session="abc", resume=True, files=False)
    assert resumed[resumed.index("--resume") + 1] == "abc"
    assert resumed[resumed.index("--tools") + 1] == "" and "--model" not in resumed
    once = cc.build_args(["claude"], system="S", session=None, files=False)
    assert "--no-session-persistence" in once and "--session-id" not in once


def test_split_command_keeps_wrapper_arguments():
    assert cc.split_command("") == ["claude"]
    assert cc.split_command(command_setting()) == [sys.executable, str(FAKE)]


def test_run_streams_and_hides_the_preamble_before_a_tool(fake, tmp_path):
    exe, calls = fake
    pieces, notes, resets = [], [], []
    args = cc.build_args(exe, system="S", session="s-1")
    reply = cc.run(args, tmp_path, "READ please", pieces.append, on_tool=notes.append, on_reset=lambda: resets.append(1))
    assert reply.text == "One\n---\nTwo\n---\nThree" and reply.session_id == "s-1"
    assert notes == ["Reading chapter-01.md..."] and resets == [1]
    assert pieces[0] == "I'll read the chapter. "
    call = calls()[-1]
    assert call["prompt"] == "READ please" and Path(call["cwd"]).resolve() == tmp_path.resolve()


def test_run_reports_login_and_missing_conversation(fake, tmp_path):
    exe, _calls = fake
    with pytest.raises(cc.ClaudeCodeError, match="not logged in"):
        cc.run(cc.build_args(exe, system="S", session="s"), tmp_path, "LOGIN", lambda t: None)
    with pytest.raises(cc.SessionMissing):
        cc.run(cc.build_args(exe, system="S", session="gone", resume=True), tmp_path, "hi", lambda t: None)
    with pytest.raises(cc.ClaudeCodeError, match="cannot run"):
        cc.run([str(tmp_path / "no-such-claude")], tmp_path, "hi", lambda t: None)


def test_run_can_be_cancelled(fake, tmp_path):
    exe, _calls = fake
    cancel = threading.Event()
    cancel.set()
    reply = cc.run(cc.build_args(exe, system="S", session="s"), tmp_path, "hi", lambda t: None, cancel=cancel)
    assert isinstance(reply, cc.Reply)


def test_sessions_are_kept_per_folder(tmp_path):
    store = cc.Sessions(tmp_path / "s.json")
    book, other = tmp_path / "book", tmp_path / "other"
    assert store.get(book) is None
    store.set(book, "a")
    store.set(book, "a")
    store.set(other, "b")
    assert store.get(book) == "a" and store.turns(book) == 2 and store.get(other) == "b"
    store.set(book, "c")
    assert store.turns(book) == 1
    store.forget(book)
    assert store.get(book) is None and store.get(other) == "b"


async def test_claude_code_conversation_continues_and_reads_files(tmp_path, fake, monkeypatch):
    _exe, calls = fake
    folder = tmp_path / "book"
    folder.mkdir()
    doc = folder / "chapter-01.md"
    doc.write_text("Mara walked her dog.\n")
    (folder / "Story Bible.md").write_text("# Story Bible\n\nThe dog is Biscuit.\n")
    settings = {"provider": "claude-code", "command": command_setting(), "model": "sonnet"}
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": settings})
    async with app.run_test(size=(120, 30)) as pilot:
        app.run_command("ai.feedback")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog")  # first use asks
        await pilot.press("a")
        assert await wait_for(pilot, lambda: app.panel.visible and app.panel.content.done)
        first = calls()[-1]
        assert "claude-code" in app.settings.plugins["ai"]["consented"]
        assert Path(first["cwd"]).resolve() == folder.resolve()
        assert "--session-id" in first["args"] and first["args"][first["args"].index("--model") + 1] == "sonnet"
        assert "The writer is working on: chapter-01.md" in first["prompt"]
        assert "Story bible: Story Bible.md" in first["prompt"]
        assert "Mara walked" not in first["prompt"]  # named, not sent
        session = first["args"][first["args"].index("--session-id") + 1]

        # An unsaved change is handed over as a copy of the editor's text.
        app.active_editor.insert("Then it rained. ")
        await pilot.press("escape")
        app.run_command("ai.summarize")
        assert await wait_for(pilot, lambda: len(calls()) == 2 and app.panel.visible and app.panel.content.done)
        second = calls()[-1]
        assert second["args"][second["args"].index("--resume") + 1] == session
        assert "unsaved changes" in second["prompt"]
        copy = tmp_path / "state" / "ai" / "current" / "chapter-01.md"
        assert "Then it rained." in copy.read_text()
        assert str(copy.parent) in second["args"]  # --add-dir for the copy

        # B adds the reply to the story bible.
        await pilot.press("b")
        assert "## From the AI Assistant" in (folder / "Story Bible.md").read_text()

        # New Conversation forgets the session.
        app.run_command("ai.new_conversation")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog")
        await pilot.press("y")
        store = cc.Sessions(tmp_path / "state" / "ai" / "claude-code-sessions.json")
        assert await wait_for(pilot, lambda: store.get(folder) is None)


async def test_claude_code_missing_program_is_explained(tmp_path, monkeypatch):
    doc = tmp_path / "d.md"
    doc.write_text("Text.\n")
    settings = {"provider": "claude-code", "command": str(tmp_path / "no-claude-here")}
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": settings})
    async with app.run_test(size=(120, 30)) as pilot:
        app.run_command("ai.feedback")
        await pilot.pause(0.2)
        assert type(app.screen).__name__ != "ConfirmDialog"
        assert not app.panel.visible
