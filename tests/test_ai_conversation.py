"""Saving a Claude Code conversation as a research note."""

import json
import sys
from pathlib import Path

from inkmill import frontmatter as fm
from inkmill.plugins import _load_package
from pluginhelp import PLUGINS, app_with, load_module, wait_for

conv = load_module("ai", "conversation")
cc = load_module("ai", "claudecode")
bb = load_module("ai", "bible")
ai = _load_package(PLUGINS / "ai")
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


def test_exchanges_pair_requests_with_replies_and_describe_them(tmp_path):
    copy = f"Project folder: /b\nThe writer is working on: /s/current/two.md (a copy of chapters/two.md with the writer's unsaved changes)"
    assert conv.request_file(copy + "\n\nHi") == "two.md"
    assert conv.request_file(HEADER + "\n\nHi") == "one.md"
    assert conv.request_file("Hi") == ""
    path = write_session(tmp_path, "s2", [
        user(f"{HEADER}\n\n{conv.FEEDBACK}\n\n{conv.WHOLE_DOCUMENT}"),
        assistant(text("## Notes\n\n**Strong** opening, weak middle.")),
        user("Is Biscuit's age consistent?"),
        assistant(text("Yes.")),
        user("LOGIN"),  # a request whose reply never came
    ])
    pairs = conv.exchanges(conv.load(path))
    assert [(e.label, e.about, e.reply) for e in pairs] == [
        ("Feedback", "one.md", "## Notes\n\n**Strong** opening, weak middle."),
        ("", "", "Yes."),
        ("", "", ""),
    ]
    assert conv.describe(pairs[0]) == "Notes"
    assert conv.describe(pairs[1]) == "Is Biscuit's age consistent?"
    bold = conv.Exchange("Summarize", "", "**Summary:** *one.md* opens.\n\n- point")
    assert conv.describe(bold) == "Summary: one.md opens."
    assert conv.describe(conv.Exchange("Feedback", "", "- First point")) == "First point"
    assert conv.describe(conv.Exchange("Ask", "x" * 100), width=20) == "x" * 17 + "..."
    assert conv.load(path) is conv.load(path)  # cached until the file changes


async def test_reply_panel_pages_through_the_claude_code_conversation(tmp_path, monkeypatch):
    home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "calls.jsonl"))
    book = tmp_path / "book"
    book.mkdir()
    doc = book / "one.md"
    doc.write_text("Mara walked her dog.\n")
    cc.Sessions(tmp_path / "state" / "ai" / "claude-code-sessions.json").set(book, "sess-2")
    write_session(home, "sess-2", [
        user(f"{HEADER}\n\nWho is Mara?\n\n{conv.WHOLE_DOCUMENT}"),
        assistant(text("Mara is the hero.")),
        user(f"{HEADER}\n\n{conv.FEEDBACK}\n\n{conv.WHOLE_DOCUMENT}"),
        assistant(text("Tighten the middle.")),
    ])
    settings = {"provider": "claude-code", "command": f'"{sys.executable}" "{FAKE}"', "consented": ["claude-code"]}
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": settings})
    async with app.run_test(size=(140, 40)) as pilot:
        editor = app.active_editor
        editor.select_range((0, 0), (0, 4))
        app.run_command("ai.ask")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "InputDialog")
        app.screen.query_one("Input").value = "Is the name good?"
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: app.panel.visible and app.panel.content.done)
        panel = app.panel.content
        title = lambda: str(app.panel.query_one("#panel-title").render())
        assert "AI: Ask (turn 3 of 3)" in title()
        request = str(panel.query_one("#ai-request").render())
        assert "Me: Ask  (one.md)" in request and "Is the name good?" in request and "> Mara" in request
        assert "R replace" in str(app.panel.query_one("#panel-hint").render())

        await pilot.press("left")
        assert panel.index == 1 and "turn 2 of 3" in title() and panel.text == "Tighten the middle."
        assert "R replace" not in str(app.panel.query_one("#panel-hint").render())
        await pilot.press("r")  # replace is for the live reply only
        assert editor.text == "Mara walked her dog.\n"
        await pilot.press("[")
        assert panel.index == 0 and panel.text == "Mara is the hero."
        await pilot.press("[")
        assert panel.index == 0
        await pilot.press("c")
        await pilot.press("right", "]")
        assert panel.index == 2

        # The list, filtered by typing.
        await pilot.press("l")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "TurnList")
        options = app.screen.query_one("OptionList")
        assert options.option_count == 3 and options.highlighted == 2
        assert "Feedback" in str(options.get_option_at_index(1).prompt)
        app.screen.query_one("Input").value = "hero"
        assert await wait_for(pilot, lambda: options.option_count == 1)
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ != "TurnList")
        assert panel.index == 0

        # AI > Conversation History opens the list without asking anything.
        await pilot.press("escape")
        # (The fake claude writes no transcript; Inkmill's log holds the two copied turns and the Ask.)
        app.run_command("ai.history")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "TurnList")
        assert app.screen.query_one("OptionList").option_count == 3
        await pilot.press("up", "enter")
        assert await wait_for(pilot, lambda: app.panel.visible and app.panel.content is not panel)
        assert app.panel.content.index == 1 and app.panel.content.text == "Tighten the middle."
        await pilot.press("i")
        assert "Tighten the middle." in editor.text

    log = conv.Log(book)
    kept = log.exchanges()
    assert [e.label for e in kept] == ["Ask", "Feedback", "Ask"]
    assert kept[2].request.startswith("Is the name good?") and kept[2].reply
    assert {r["session"] for r in log.records()} == {"sess-2"}


def test_log_syncs_claude_code_turns_once_and_marks_new_conversations(tmp_path):
    log = conv.Log(tmp_path)
    turns = [conv.Exchange("Ask", "a?", "A.", time="2026-11-01T00:00:00Z"),
             conv.Exchange("Feedback", "", "F.", time="2026-11-02T00:00:00Z")]
    assert log.sync("s1", turns[:1]) == 1
    assert log.sync("s1", turns) == 1 and log.sync("s1", turns) == 0
    log.append(conv.Exchange("Ask", "b?", "B.", time="2026-10-01T00:00:00Z"), provider="ollama")
    assert [e.request for e in log.exchanges()] == ["b?", "a?", ""]  # oldest first
    log.reset()
    assert log.exchanges(since_reset=True) == [] and len(log.exchanges()) == 3
    (log.path).write_text(log.path.read_text() + "not json\n")
    assert len(log.records()) == 4
    assert conv.stamp("2026-11-11T06:12:00.123Z") == "2026-11-11T06:12:00Z"
    assert conv.stamp("2026-11-11T16:12:00+10:00") == "2026-11-11T06:12:00Z"


def test_saved_note_reads_back_as_turns():
    turns = [
        conv.Turn("me", "(About the whole document.)", "Feedback"),
        conv.Turn("claude", "## What works\n\nThe opening.\n\n```\n## kept\n```", looked_at=["one.md", "Grep x"]),
        conv.Turn("me", "Who is Mara?"),
        conv.Turn("claude", "The hero."),
    ]
    note = "---\ntitle: Chat\ntype: research\n---\n" + conv.to_markdown(turns, "Chat", "Saved today.")
    assert conv.is_saved_conversation(note) and not conv.is_saved_conversation("# A chapter\n\nMe and Claude.")
    back = conv.from_markdown(note)
    assert [(e.label, e.request) for e in back] == [("Feedback", "(About the whole document.)"), ("", "Who is Mara?")]
    assert back[0].reply == "## What works\n\nThe opening.\n\n```\n## kept\n```"
    assert back[0].looked_at == ["one.md", "Grep x"] and back[1].reply == "The hero."


def test_seeded_request_reads_without_the_earlier_conversation(tmp_path):
    seeded = f"{conv.SEED_START}This is a new conversation...\n{conv.SEED_END}\n\n{HEADER}\n\n{conv.FEEDBACK}\n\n{conv.WHOLE_DOCUMENT}"
    path = write_session(tmp_path, "s3", [user(seeded), assistant(text("Fine."))])
    turns = conv.turns(path)
    assert (turns[0].label, turns[0].about, turns[0].text) == ("Feedback", "one.md", "(About the whole document.)")
    assert turns[0].time == ""  # these records carry no timestamp


async def test_new_conversation_gets_the_turns_claude_code_lost(tmp_path, monkeypatch):
    home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(calls))
    book = tmp_path / "book"
    book.mkdir()
    doc = book / "one.md"
    doc.write_text("Mara walked her dog.\n")
    conv.Log(book).append(conv.Exchange("Ask", "Who is Mara?", "The hero.", time="2026-10-01T00:00:00Z"),
                          session="gone", provider="claude-code")
    cc.Sessions(tmp_path / "state" / "ai" / "claude-code-sessions.json").set(book, "gone")
    settings = {"provider": "claude-code", "command": f'"{sys.executable}" "{FAKE}"', "consented": ["claude-code"]}
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": settings})
    async with app.run_test(size=(140, 40)) as pilot:
        app.run_command("ai.feedback")
        assert await wait_for(pilot, lambda: app.panel.visible and app.panel.content.done)
        panel = app.panel.content
        assert [e.reply for e in panel.entries][0] == "The hero." and panel.index == 1
        # Asked again: the conversation is resumed, and nothing is put in front.
        app.run_command("ai.feedback")
        assert await wait_for(pilot, lambda: app.panel.content is not panel and app.panel.content.done)
    sent = [json.loads(line) for line in calls.read_text().splitlines()]
    assert "--resume" in sent[0]["args"] and not sent[0]["prompt"].startswith(conv.SEED_START)
    assert sent[1]["prompt"].startswith(conv.SEED_START) and "--session-id" in sent[1]["args"]
    earlier = book / ".inkmill" / "earlier-conversation.md"
    assert str(earlier) in sent[1]["prompt"] and "Who is Mara?" in earlier.read_text()
    assert "--resume" in sent[2]["args"] and not sent[2]["prompt"].startswith(conv.SEED_START)
    assert len(conv.Log(book).exchanges()) == 3


async def test_new_conversation_command_starts_without_the_earlier_turns(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(calls))
    doc = tmp_path / "one.md"
    doc.write_text("Text.\n")
    conv.Log(tmp_path).append(conv.Exchange("Ask", "Q?", "A."), session="s0")
    cc.Sessions(tmp_path / "state" / "ai" / "claude-code-sessions.json").set(tmp_path, "s0")
    settings = {"provider": "claude-code", "command": f'"{sys.executable}" "{FAKE}"', "consented": ["claude-code"]}
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": settings})
    async with app.run_test(size=(140, 40)) as pilot:
        app.run_command("ai.new_conversation")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog")
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ != "ConfirmDialog")
        app.run_command("ai.feedback")
        assert await wait_for(pilot, lambda: app.panel.visible and app.panel.content.done)
        assert len(app.panel.content.entries) == 2  # the history still shows the earlier turn
    sent = json.loads(calls.read_text().splitlines()[0])
    assert "--session-id" in sent["args"] and not sent["prompt"].startswith(conv.SEED_START)


async def test_show_saved_conversation_pages_a_note(tmp_path):
    note = tmp_path / "chat.md"
    turns = [conv.Turn("me", "Who is Mara?", "Ask"), conv.Turn("claude", "The hero."),
             conv.Turn("me", "And Biscuit?", "Ask"), conv.Turn("claude", "The dog.")]
    note.write_text("---\ntitle: Chat\ntype: research\n---\n" + conv.to_markdown(turns, "Chat"))
    app = app_with(tmp_path, "ai", paths=[note])
    async with app.run_test(size=(140, 40)) as pilot:
        app.run_command("ai.show_saved")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "TurnList")
        assert app.screen.query_one("OptionList").option_count == 2
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: app.panel.visible)
        assert app.panel.content.text == "The dog."
        await pilot.press("left")
        assert app.panel.content.text == "The hero."


def test_import_conversation_from_claude_code_and_notes(tmp_path, monkeypatch, capsys):
    from inkmill.__main__ import main

    home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.setattr("inkmill.plugins.plugins_dir", lambda: PLUGINS)
    monkeypatch.setattr(ai, "state_dir", lambda: tmp_path / "state")
    book = tmp_path / "book"
    book.mkdir()
    records = [user(f"{HEADER}\n\nWho is Mara?\n\n{conv.WHOLE_DOCUMENT}"), assistant(text("The hero."))]
    for r in records:
        r["cwd"] = str(book)
        r["timestamp"] = "2026-11-01T00:00:00.000Z"
    write_session(home, "old-1", records)
    cc.Sessions(tmp_path / "state" / "ai" / "claude-code-sessions.json").set(book, "old-1")

    assert ai.import_conversation(book) == [
        "Claude Code conversation old-1: 1 of 1 turn(s) added", f"Kept in {conv.Log(book).path}"]
    assert ai.import_conversation(book, "all")[0] == "Claude Code conversation old-1: 0 of 1 turn(s) added"

    note = tmp_path / "chat.md"
    note.write_text("---\ntitle: Chat\nsaved: 2026-10-05\n---\n" + conv.to_markdown(
        [conv.Turn("me", "Who is Mara?\n\n(About the whole document.)", "Ask"), conv.Turn("claude", "The hero."),
         conv.Turn("me", "Older?"), conv.Turn("claude", "Yes.")], "Chat"))
    assert main(["--import-conversation", str(book), "--from", str(note)]) == 0
    assert "chat.md: 1 of 2 turn(s) added" in capsys.readouterr().out
    kept = conv.Log(book).exchanges()
    assert [e.request for e in kept] == ["Older?", "Who is Mara?\n\n(About the whole document.)"]
    assert kept[0].time == "2026-10-05T00:00:00Z"
    assert main(["--import-conversation", str(book), "--from", "nope"]) == 1
    assert main(["--import-conversation", str(tmp_path / "missing")]) == 1


BIBLE = """# Story Bible

Intro.

## Characters

- Mara, the hero.

## Places

## Style

Plain.
"""


def test_bible_entries_are_read_and_filed_under_their_headings():
    assert bb.sections(BIBLE + "```\n## not one\n```\n") == ["Characters", "Places", "Style"]
    reply = 'Here you go:\n```json\n[{"section": "characters", "entry": "Biscuit is  her dog.", "note": ""},' \
            ' {"section": "Places", "entry": "The harbor.", "note": "the bible says a lake"},' \
            ' {"section": "Plot", "entry": "Mara leaves in chapter 3."}, {"section": "X", "entry": ""}]\n```'
    found = bb.parse(reply)
    assert [(p.section, p.entry, p.note) for p in found] == [
        ("characters", "Biscuit is her dog.", ""), ("Places", "The harbor.", "the bible says a lake"),
        ("Plot", "Mara leaves in chapter 3.", "")]
    assert bb.parse("No JSON here.") is None and bb.parse("[]") == []
    merged = bb.merge(BIBLE, found)
    assert merged == """# Story Bible

Intro.

## Characters

- Mara, the hero.
- Biscuit is her dog.

## Places

- The harbor.

## Style

Plain.

## Plot

- Mara leaves in chapter 3.
"""
    assert "Characters, Places, Style" in bb.request("Talk.", "", ["Characters", "Places", "Style"])


async def test_update_story_bible_from_the_conversation(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(calls))
    monkeypatch.setenv("FAKE_CLAUDE_REPLY", json.dumps([
        {"section": "Characters", "entry": "Biscuit is Mara's dog.", "note": ""},
        {"section": "Places", "entry": "A lake town.", "note": ""}]))
    doc = tmp_path / "one.md"
    doc.write_text("Mara walked her dog.\n")
    (tmp_path / "Story Bible.md").write_text(BIBLE)
    conv.Log(tmp_path).append(conv.Exchange("Ask", "Name the dog?", "Biscuit, settled."))
    settings = {"provider": "claude-code", "command": f'"{sys.executable}" "{FAKE}"', "consented": ["claude-code"]}
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": settings})
    async with app.run_test(size=(140, 40)) as pilot:
        app.run_command("ai.bible_update")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "BibleReview", timeout=10)
        review = app.screen
        assert review.query_one("OptionList").option_count == 2 and review.chosen() == [0, 1]
        await pilot.press("down", "space")  # uncheck the lake town
        assert review.chosen() == [0]
        await pilot.press("enter", "enter")  # Enter toggles too
        assert review.chosen() == [0]
        await pilot.press("a")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ != "BibleReview")
    text = (tmp_path / "Story Bible.md").read_text()
    assert "- Mara, the hero.\n- Biscuit is Mara's dog.\n" in text and "lake" not in text
    sent = json.loads(calls.read_text().splitlines()[0])
    assert "--no-session-persistence" in sent["args"]  # kept out of the conversation
    saved = tmp_path / ".inkmill" / "conversation-for-bible.md"
    assert str(saved) in sent["prompt"] and "Name the dog?" in saved.read_text()
    assert len(conv.Log(tmp_path).exchanges()) == 1  # not added to the history either


async def test_update_story_bible_with_nothing_to_go_on(tmp_path):
    doc = tmp_path / "one.md"
    doc.write_text("Text.\n")
    app = app_with(tmp_path, "ai", paths=[doc])
    async with app.run_test(size=(140, 40)) as pilot:
        app.run_command("ai.bible_update")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ not in ("BibleReview", "ConfirmDialog")
