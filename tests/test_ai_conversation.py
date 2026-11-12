"""Saving a Claude Code conversation as a research note."""

import json
import sys
from pathlib import Path

from inkmill import frontmatter as fm
from pluginhelp import app_with, load_module, wait_for

conv = load_module("ai", "conversation")
cc = load_module("ai", "claudecode")
FAKE = Path(__file__).with_name("fake_claude.py")
HEADER = "Project folder: /book\nBinder (chapter order and research list): book.md\nThe writer is working on: chapters/one.md"


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def assistant(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


def text(t):
    return {"type": "text", "text": t}


def read(path):
    return {"type": "tool_use", "name": "Read", "input": {"file_path": path}}


def write_session(home: Path, session: str, records) -> Path:
    folder = home / "projects" / "-book"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session}.jsonl"
    lines = [json.dumps(r) for r in records]
    path.write_text("\n".join(lines[:1] + ["not json"] + lines[1:]) + "\n", encoding="utf-8")
    return path


def test_requests_lose_the_file_note_and_name_their_command():
    assert conv.clean_request(f"{HEADER}\n\n{conv.FEEDBACK}\n\n{conv.WHOLE_DOCUMENT}") == (
        "Feedback", "(About the whole document.)")
    label, body = conv.clean_request(f"{HEADER}\n\nWho is Mara?\n\n{conv.PASSAGE}Mara ran.\n\nShe hid.")
    assert label == "Ask" and body == "Who is Mara?\n\nAbout this passage:\n\n> Mara ran.\n>\n> She hid."
    label, body = conv.clean_request(f"{HEADER}\n\n{conv.REWRITE.format(how='warmer')}\n\nMara ran.")
    assert label == "Rewrite (warmer)" and body == "> Mara ran."
    assert conv.clean_request(f"{HEADER}\n\nRead every chapter:\n- a.md\n\n{conv.CONTINUITY}") == ("Continuity Check", "")
    # Without file access the document and story bible came first; only the request is kept.
    label, body = conv.clean_request(f"{conv.BIBLE}The dog is Biscuit.\n\n{conv.SUMMARY}\n\n{conv.TEXT}Mara walked.")
    assert label == "Summarize" and body == "(About the whole document.)"
    # Typed in Claude Code itself: unchanged.
    assert conv.clean_request("What about chapter 3?") == ("", "What about chapter 3?")


def test_turns_keep_requests_and_final_reply_text(tmp_path):
    path = write_session(tmp_path, "s1", [
        {"type": "queue-operation"},
        user(f"{HEADER}\n\n{conv.FEEDBACK}\n\n{conv.WHOLE_DOCUMENT}"),
        assistant(text("I'll read the chapter.")),
        assistant(read("/book/chapters/one.md")),
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "1\tMara"}]}},
        assistant({"type": "thinking", "thinking": "hmm"}),
        assistant(text("## What works\n\nThe opening.")),
        assistant(text("```\n# not a heading\n```")),
        {"type": "user", "isMeta": True, "message": {"content": "meta"}},
        user("And chapter two?"),
        assistant(text("Also good.")),
    ])
    turns = conv.turns(path)
    assert [(t.role, t.label) for t in turns] == [("me", "Feedback"), ("claude", ""), ("me", ""), ("claude", "")]
    assert turns[1].looked_at == ["one.md"]
    assert "I'll read" not in turns[1].text
    md = conv.to_markdown(turns, "Chat", "Saved today.")
    assert md.startswith("# Chat\n\nSaved today.\n\n## Me: Feedback\n\n(About the whole document.)\n\n## Claude\n\n_Looked at: one.md_")
    assert "#### What works" in md and "```\n# not a heading\n```" in md
    assert "## Me\n\nAnd chapter two?\n\n## Claude\n\nAlso good.\n" in md
    assert "Project folder" not in md


def test_find_uses_claude_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    path = write_session(tmp_path, "abc-123", [user("hi")])
    assert conv.find("abc-123") == path
    assert conv.find("missing") is None and conv.find("../x") is None


async def test_save_conversation_adds_a_research_note_to_the_binder(tmp_path, monkeypatch):
    home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    book = tmp_path / "book"
    (book / "chapters").mkdir(parents=True)
    binder = book / "book.md"
    binder.write_text("---\ntitle: The Book\ncontents:\n  - chapters/one.md\n---\n")
    chapter = book / "chapters" / "one.md"
    chapter.write_text("---\ntitle: One\nparent: ../book.md\n---\nMara walked her dog.\n")
    cc.Sessions(tmp_path / "state" / "ai" / "claude-code-sessions.json").set(book, "sess-1")
    write_session(home, "sess-1", [
        user(f"{HEADER}\n\n{conv.FEEDBACK}\n\n{conv.WHOLE_DOCUMENT}"),
        assistant(read(str(chapter))),
        assistant(text("The dog needs a name.")),
    ])
    settings = {"provider": "claude-code", "command": f'"{sys.executable}" "{FAKE}"'}
    app = app_with(tmp_path, "ai", "binder", paths=[chapter], plugins={"ai": settings})
    async with app.run_test(size=(120, 30)) as pilot:
        app.run_command("ai.save_conversation")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "InputDialog")
        from textual.widgets import Input

        app.screen.query_one(Input).value = "Naming the dog"
        await pilot.press("enter")
        note = book / "research" / "naming-the-dog.md"
        assert await wait_for(pilot, lambda: app.active_document.path is not None
                              and app.active_document.path.resolve() == note.resolve())
        saved = note.read_text()
        meta = fm.read(saved)
        assert meta["type"] == "research" and meta["source"] == "claude-code session sess-1"
        assert meta["parent"] == "../book.md"
        assert "## Me: Feedback" in saved and "The dog needs a name." in saved and "_Looked at: one.md_" in saved
        assert "research/naming-the-dog.md" in fm.read(binder.read_text())["research"]

        # A second save never overwrites the first.
        app.run_command("ai.save_conversation")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "InputDialog")
        app.screen.query_one(Input).value = "Naming the dog"
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: (book / "research" / "naming-the-dog-2.md").exists())
