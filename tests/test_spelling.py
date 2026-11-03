from pluginhelp import app_with, load_module, wait_for

checker_mod = load_module("spelling", "checker")


def test_checker_finds_errors_and_ranks_suggestions():
    c = checker_mod.Checker()
    text = "Teh quay was recieve. See `codez` at http://x.y/zzq [^n1]. NASA in Paris, not paris."
    assert [w for _, _, w in c.errors(text)] == ["Teh", "recieve", "paris"]
    assert c.suggest("Teh")[0] == "The"
    assert c.suggest("thier")[0] == "their"
    assert c.suggest("alot")[0] == "a lot"


def test_personal_dictionary(tmp_path):
    personal = tmp_path / "dicts" / "personal.txt"
    c = checker_mod.Checker([tmp_path / "dicts"], personal)
    assert not c.known("Inkmill")
    c.add_to_personal("Inkmill")
    assert checker_mod.Checker([tmp_path / "dicts"], personal).known("Inkmill")


async def test_underline_and_check_dialog(tmp_path):
    doc = tmp_path / "d.md"
    doc.write_text("Teh ferry left.\n")
    app = app_with(tmp_path, "spelling", paths=[doc])
    async with app.run_test(size=(100, 30)) as pilot:
        editor = app.active_editor
        assert await wait_for(pilot, lambda: editor.decorations("spelling"))
        assert editor.decorations("spelling")[0][:2] == ((0, 0), (0, 3))
        await pilot.press("ctrl+f2")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "SpellDialog")
        await pilot.press("enter")  # first suggestion
        assert await wait_for(pilot, lambda: editor.text.startswith("The ferry"))
        assert await wait_for(pilot, lambda: not editor.decorations("spelling"))


async def test_underline_is_actually_drawn(tmp_path):
    doc = tmp_path / "d.md"
    doc.write_text("Teh boat.\n")
    app = app_with(tmp_path, "spelling", paths=[doc])
    async with app.run_test() as pilot:
        editor = app.active_editor
        assert await wait_for(pilot, lambda: editor.decorations("spelling"))
        await pilot.pause(0.1)
        flags = [bool(seg.style and seg.style.underline) for seg in editor.render_line(0) for _ in seg.text]
        assert flags[:3] == [True, True, True]
        assert not any(flags[3:9])
