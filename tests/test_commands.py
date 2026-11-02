import pytest

from inkmill.commands import Command, CommandRegistry, format_key
from inkmill.menus import Menu, MenuItem, MenuModel, Separator, split_accelerator


def test_registry_and_overrides():
    reg = CommandRegistry()

    @reg.add("a.one", "One", "ctrl+o")
    def one(app):
        return 1

    reg.register(Command("a.two", "Two", lambda app: 2, keys=("ctrl+o",)))
    assert "a.one" in reg and len(reg) == 2
    assert reg.key_conflicts() == {"ctrl+o": ["a.one", "a.two"]}
    unknown = reg.apply_key_overrides({"a.two": "f2, f3", "missing": "x"})
    assert reg.get("a.two").keys == ("f2", "f3")
    assert unknown == ["missing"]
    with pytest.raises(ValueError):
        reg.register(Command("a.one", "dup", lambda app: None))


def test_format_key():
    assert format_key("ctrl+s") == "^S"
    assert format_key("f5") == "F5"
    assert format_key("shift+f3") == "Shift+F3"
    assert format_key("alt+equals_sign") == "Alt+="
    assert format_key("escape") == "Esc"


def test_accelerators():
    assert split_accelerator("F&ormat") == ("Format", "o", 1)
    assert split_accelerator("Plain") == ("Plain", "p", 0)


def test_menu_model_insertion():
    model = MenuModel()
    model.add_menu(Menu("file", "&File", [MenuItem("x"), MenuItem("z")]))
    model.add_menu(Menu("help", "&Help"))
    tools = model.ensure("tools", "&Tools")
    assert [m.id for m in model] == ["file", "tools", "help"]
    assert model.ensure("tools", "ignored") is tools
    file_menu = model.get("file")
    file_menu.add(MenuItem("y"), after="x")
    file_menu.add(Separator(), before="z")
    assert [getattr(i, "command", "-") for i in file_menu.items] == ["x", "y", "-", "z"]
    assert file_menu.remove("y")
