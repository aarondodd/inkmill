"""Menu model.

Menus are data: an ordered list of :class:`Menu` objects, each holding items
that reference commands by id. Labels may mark their accelerator letter with
``&`` (``"&File"``); without a marker the first letter is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Union


@dataclass
class MenuItem:
    command: str
    label: str | None = None  # Defaults to the command's label.


@dataclass
class Separator:
    pass


Entry = Union[MenuItem, Separator]


def split_accelerator(label: str) -> tuple[str, str | None, int]:
    """Return (plain label, accelerator letter, index of that letter)."""
    idx = label.find("&")
    if idx != -1 and idx + 1 < len(label):
        plain = label[:idx] + label[idx + 1 :]
        return plain, plain[idx].lower(), idx
    for i, ch in enumerate(label):
        if ch.isalnum():
            return label, ch.lower(), i
    return label, None, -1


@dataclass
class Menu:
    id: str
    label: str
    items: list[Entry] = field(default_factory=list)

    @property
    def title(self) -> str:
        return split_accelerator(self.label)[0]

    @property
    def accelerator(self) -> str | None:
        return split_accelerator(self.label)[1]

    def add(self, item: Entry, *, after: str | None = None, before: str | None = None) -> None:
        anchor = after or before
        if anchor is not None:
            for i, existing in enumerate(self.items):
                if isinstance(existing, MenuItem) and existing.command == anchor:
                    self.items.insert(i + 1 if after else i, item)
                    return
        self.items.append(item)

    def remove(self, command: str) -> bool:
        for i, existing in enumerate(self.items):
            if isinstance(existing, MenuItem) and existing.command == command:
                del self.items[i]
                return True
        return False


class MenuModel:
    def __init__(self) -> None:
        self._menus: list[Menu] = []

    def add_menu(self, menu: Menu, *, before: str | None = None) -> Menu:
        if self.get(menu.id) is not None:
            raise ValueError(f"menu {menu.id!r} already exists")
        if before is not None:
            for i, existing in enumerate(self._menus):
                if existing.id == before:
                    self._menus.insert(i, menu)
                    return menu
        self._menus.append(menu)
        return menu

    def get(self, id: str) -> Menu | None:
        return next((m for m in self._menus if m.id == id), None)

    def ensure(self, id: str, label: str, *, before: str | None = "help") -> Menu:
        return self.get(id) or self.add_menu(Menu(id, label), before=before)

    def __iter__(self) -> Iterator[Menu]:
        return iter(self._menus)

    def __len__(self) -> int:
        return len(self._menus)

    def index(self, id: str) -> int:
        for i, menu in enumerate(self._menus):
            if menu.id == id:
                return i
        raise KeyError(id)
