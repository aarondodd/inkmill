from pluginhelp import app_with, load_module, wait_for

model = load_module("outline", "model")

DOC = """---
title: x
---
# One
a
## One.A
b
# Two
```
# not a heading
```
c
Three
=====
d
"""


def test_headings_skip_code_and_front_matter():
    heads = model.headings(DOC)
    assert [(h.level, h.title) for h in heads] == [(1, "One"), (2, "One.A"), (1, "Two"), (1, "Three")]


def test_move_and_shift_sections():
    new, line = model.move_section(DOC, 2, -1)  # Two above One
    titles = [h.title for h in model.headings(new)]
    assert titles == ["Two", "One", "One.A", "Three"]
    assert new.split("\n")[line] == "# Two"
    assert model.move_section(DOC, 1, -1) is None  # One.A has no earlier sibling
    demoted = model.shift_level(DOC, 0, 1)
    assert [(h.level, h.title) for h in model.headings(demoted)][:2] == [(2, "One"), (3, "One.A")]
    assert model.shift_level(DOC, 1, 5) is None


async def test_outline_panel_jumps_and_moves(tmp_path):
    from textual.widgets import OptionList

    doc = tmp_path / "d.md"
    doc.write_text(DOC)
    app = app_with(tmp_path, "outline", paths=[doc])
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("f8")
        assert await wait_for(pilot, lambda: app.panel.visible)
        option_list = app.panel.query_one(OptionList)
        assert option_list.option_count == 4
        option_list.highlighted = 2
        await pilot.press("[")
        assert await wait_for(pilot, lambda: app.active_document.text.split("\n")[3] == "# Two")
        await pilot.press("down", "enter")
        await pilot.pause(0.1)
        assert app.focused is app.active_editor
        await pilot.press("ctrl+t")
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not app.panel.visible
