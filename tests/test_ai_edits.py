"""AI Assistant: Continue Writing, and Suggest Edits as tracked changes."""

import json
import sys
from pathlib import Path

from inkmill.plugins import _load_package
from pluginhelp import PLUGINS, app_with, load_module, wait_for

ai = _load_package(PLUGINS / "ai")
ed = ai.edits
conv = ai.conversation
critic = load_module("comments", "critic")
FAKE = Path(__file__).with_name("fake_claude.py")


def settings():
    return {"provider": "claude-code", "command": f'"{sys.executable}" "{FAKE}"', "consented": ["claude-code"]}


def fake(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "calls.jsonl"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def sent(tmp_path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]


# -- the pieces --------------------------------------------------------------------


def test_edits_are_read_placed_in_order_and_written_as_changes():
    reply = '```json\n[{"find": "teh", "replace": "the", "why": "typo"}, {"find": "the cat", "replace": "it"},' \
            ' {"find": "absent", "replace": "x"}, {"find": "same", "replace": "same"}, 7]\n```'
    found = ed.parse(reply)
    assert [e.find for e in found] == ["teh", "the cat", "absent"]
    assert ed.parse("I would change a few things.") is None
    text = "the cat sat on teh mat and the cat ran."
    placed, missed = ed.locate(text, found)
    # "the cat" after "teh" lands on the second occurrence, in document order.
    assert [(p.start, p.edit.find) for p in placed] == [(15, "teh"), (27, "the cat")]
    assert [e.find for e in missed] == ["absent"]
    assert ed.marked(text, placed) == "the cat sat on {~~teh~>the~~}{>>typo<<} mat and {~~the cat~>it~~} ran."
    assert ed.applied(text, placed) == "the cat sat on the mat and it ran."
    marked = ed.marked(text, placed)
    assert critic.resolve(marked, accept=True) == ed.applied(text, placed)
    assert critic.resolve(marked, accept=False) == text


def test_edits_that_overlap_or_touch_markup_are_left_out():
    text = "One {--two--} three four."
    placed, missed = ed.locate(text, [ed.Edit("two", "2"), ed.Edit("three four", "3 4"), ed.Edit("three", "3"),
                                       ed.Edit("four", "a {++b++}")])
    assert [p.edit.find for p in placed] == ["three", "four"]
    assert [e.find for e in missed] == ["two", "three", "four"]
    deletion = ed.locate("Cut this.", [ed.Edit(" this", "", "wordy")])[0]
    assert ed.marked("Cut this.", deletion) == "Cut{-- this--}{>>wordy<<}."
    assert ed.to_markdown([ed.Edit("a", "b", "why"), ed.Edit("c", "")]) == "- 'a' -> 'b' (why)\n- delete 'c'"


def test_edits_are_narrowed_to_the_words_that_change():
    text = "his knees aching with every every step. Their was a storm. the dog ran"
    cases = [("with every every step", "with every step", "with every {--every --}step"),
             ("Their was a storm", "There was a storm", "{~~Their~>There~~} was"),
             ("the dog ran", "the big dog ran", "the{++ big++} dog ran")]
    for find, replace, shown in cases:
        placed, _ = ed.locate(text, [ed.Edit(find, replace)])
        assert shown in ed.marked(text, placed)
        assert ed.applied(text, placed) == text.replace(find, replace)
    assert ed.Edit("", "big ").label() == "add 'big '"
    # Two fixes folded into one edit come apart; the reason stays with the first.
    placed, _ = ed.locate("Their was a storm comming in.", [ed.Edit("Their was a storm comming", "There was a storm coming", "spelling")])
    assert [(p.edit.find, p.edit.replace, p.edit.why) for p in placed] == [("Their", "There", "spelling"), ("comming", "coming", "")]
    assert ed.marked("Their was a storm comming in.", placed) == "{~~Their~>There~~}{>>spelling<<} was a storm {~~comming~>coming~~} in."


def test_continuation_joins_the_text_around_it():
    assert ed.join("He said", " hello.") == " hello."
    assert ed.join("He said", "hello.") == " hello."
    assert ed.join("He said ", "hello.") == "hello."
    assert ed.join("Word", ", then more") == ", then more"
    assert ed.join("End.\n", "\n\nNew paragraph.") == "\nNew paragraph."
    assert ed.join("End.", "\n\nNew paragraph.", "Next.") == "\n\nNew paragraph.\n\n"
    assert ed.join("", "Start.") == "Start."
    assert ed.join("Mid", "dle", " rest") == " dle"
    assert ed.join("A", "B", "C") == " B "
    assert ed.join("A", "   ") == ""


def test_requests_are_named_in_the_history():
    request = f"{ed.request('tighten it.')}\n\n{conv.WHOLE_DOCUMENT}"
    assert conv.clean_request(request, from_inkmill=True) == ("Suggest Edits (tighten it)", "(About the whole document.)")
    passage = "x" * 400 + " the end"
    request = f"{conv.CONTINUE} Write about 300 words.\n\n{conv.ENDS_HERE}{passage}\n\n{conv.FOLLOWS}After."
    label, about = conv.clean_request(request, from_inkmill=True)
    assert label == "Continue" and about.startswith("Write about 300 words.") and "Continuing after:" in about
    assert about.endswith("the end") and "After." not in about and len(about) < 400


def test_a_suggestion_and_its_reason_are_one_review_item():
    text = "A {~~red~>blue~~}{>>sky color<<} and {++new ++}{>>clearer<<}{--old--} word {==x==}{>>note<<}."
    found = critic.marks(text)
    assert [(m.kind, m.note) for m in found] == [("replace", "sky color"), ("add", "clearer"), ("delete", ""),
                                                 ("highlight", "note")]
    assert found[0].label() == "change 'red' to 'blue' (sky color)"
    assert critic.resolve(text, accept=True) == "A blue and new  word x."
    assert critic.resolve(text, accept=False) == "A red and old word x."
    html = critic.to_html(text)
    assert html.count("critic-comment") == 3 and "sky color" in html


# -- in the app --------------------------------------------------------------------


async def test_continue_writing_inserts_where_the_cursor_was(tmp_path, monkeypatch):
    fake(monkeypatch, tmp_path, FAKE_CLAUDE_CONTINUE="She ran to the lake.")
    doc = tmp_path / "one.md"
    doc.write_text("Mara walked her dog.\n\nThe end.\n")
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": settings()})
    async with app.run_test(size=(140, 40)) as pilot:
        editor = app.active_editor
        editor.move_cursor((0, len("Mara walked her dog.")))
        app.run_command("ai.continue")
        assert await wait_for(pilot, lambda: app.panel.visible and app.panel.content.done, timeout=10)
        panel = app.panel.content
        assert "AI: Continue" in str(app.panel.query_one("#panel-title").render())
        assert "Continuing after:" in str(panel.query_one("#ai-request").render())
        editor.move_cursor((2, 3))  # the writer moved on while it was writing
        panel.focus()
        await pilot.press("i")
        assert editor.text == "Mara walked her dog. She ran to the lake.\n\nThe end.\n"
        assert editor.cursor_location == (0, len("Mara walked her dog. She ran to the lake."))
    prompt = sent(tmp_path)[0]["prompt"]
    assert conv.CONTINUE in prompt and "Write about 300 words." in prompt
    assert f"{conv.ENDS_HERE}Mara walked her dog." in prompt and f"{conv.FOLLOWS}\n\nThe end." in prompt
    assert [e.label for e in conv.Log(tmp_path).exchanges()] == ["Continue"]


async def test_continue_writing_falls_back_to_the_cursor_when_the_text_changed(tmp_path, monkeypatch):
    fake(monkeypatch, tmp_path)
    doc = tmp_path / "one.md"
    doc.write_text("First.\n")
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": settings()})
    async with app.run_test(size=(140, 40)) as pilot:
        editor = app.active_editor
        editor.move_cursor((0, 6))
        app.run_command("ai.continue")
        assert await wait_for(pilot, lambda: app.panel.visible and app.panel.content.done, timeout=10)
        editor.replace("Changed", (0, 0), (0, 5))
        editor.move_cursor((0, 0))
        app.panel.content.focus()
        await pilot.press("i")
        assert editor.text == "She ran. Changed.\n"


async def test_suggested_edits_are_marked_for_review(tmp_path, monkeypatch):
    fake(monkeypatch, tmp_path, FAKE_CLAUDE_REPLY=json.dumps([
        {"find": "teh", "replace": "the", "why": "typo"},
        {"find": "very very", "replace": "very", "why": "repeated"},
        {"find": "not in the text", "replace": "x"}]))
    doc = tmp_path / "one.md"
    doc.write_text("---\ntitle: teh\n---\nMara walked teh very very big dog.\n")
    app = app_with(tmp_path, "ai", "comments", paths=[doc], plugins={"ai": settings()})
    async with app.run_test(size=(140, 40)) as pilot:
        editor = app.active_editor
        app.run_command("ai.suggest_edits")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "InputDialog")
        app.screen.query_one("Input").value = "fix typos"
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: "{~~" in editor.text, timeout=10)
        # The front matter is left alone; the unmatched edit is dropped.
        assert editor.text == ("---\ntitle: teh\n---\nMara walked {~~teh~>the~~}{>>typo<<} "
                               "very{-- very--}{>>repeated<<} big dog.\n")
        assert await wait_for(pilot, lambda: app.panel.visible and type(app.panel.content).__name__ == "ReviewList")
        review = app.panel.content
        assert review.option_count == 2
        review.focus()
        review.highlighted = 0
        await pilot.press("a")  # accept the typo fix
        assert await wait_for(pilot, lambda: review.option_count == 1)
        review.highlighted = 0
        await pilot.press("r")  # keep "very very"
        assert editor.text == "---\ntitle: teh\n---\nMara walked the very very big dog.\n"
    prompt = sent(tmp_path)[0]["prompt"]
    assert "Suggest edits to the text: fix typos." in prompt and conv.WHOLE_DOCUMENT in prompt
    assert "--no-session-persistence" not in sent(tmp_path)[0]["args"]  # part of the conversation
    kept = conv.Log(tmp_path).exchanges()
    assert [e.label for e in kept] == ["Suggest Edits (fix typos)"]
    assert kept[0].reply.startswith("- 'teh' -> 'the' (typo)")


async def test_suggested_edits_without_track_changes_are_picked_from_a_list(tmp_path, monkeypatch):
    fake(monkeypatch, tmp_path, FAKE_CLAUDE_REPLY=json.dumps([
        {"find": "teh", "replace": "the", "why": "typo"}, {"find": " big", "replace": "", "why": "filler"}]))
    doc = tmp_path / "one.md"
    doc.write_text("Before. Mara walked teh big dog. After teh end.\n")
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": settings()})
    async with app.run_test(size=(140, 40)) as pilot:
        editor = app.active_editor
        editor.select_range((0, 8), (0, 32))  # "Mara walked teh big dog."
        app.run_command("ai.suggest_edits")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "InputDialog")
        await pilot.press("enter")  # the default request
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "EditReview"
                              and app.screen.query("OptionList"), timeout=10)
        review = app.screen
        assert review.chosen() == [0, 1]
        await pilot.press("down", "space")  # keep "big"
        await pilot.press("a")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ != "EditReview")
        # Only the selection changes; the "teh" after it is not part of the request.
        assert editor.text == "Before. Mara walked the big dog. After teh end.\n"
    prompt = sent(tmp_path)[0]["prompt"]
    assert "fix spelling, grammar and clumsy phrasing" in prompt and "Mara walked teh big dog." in prompt


async def test_suggested_edits_that_are_not_a_list_show_in_the_panel(tmp_path, monkeypatch):
    fake(monkeypatch, tmp_path, FAKE_CLAUDE_REPLY="It reads well; I would not change anything.")
    doc = tmp_path / "one.md"
    doc.write_text("Text.\n")
    app = app_with(tmp_path, "ai", "comments", paths=[doc], plugins={"ai": settings()})
    async with app.run_test(size=(140, 40)) as pilot:
        app.run_command("ai.suggest_edits")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "InputDialog")
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: app.panel.visible and type(app.panel.content).__name__ == "ReplyPanel",
                              timeout=10)
        assert "reads well" in app.panel.content.text
        assert app.active_editor.text == "Text.\n"
