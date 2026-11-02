"""Command registry.

Every user-facing action in Inkmill is a :class:`Command`. Menus, key bindings
and the command palette are all views over this one registry, so a plugin that
registers a command gets a key binding, a palette entry and (optionally) a menu
item without touching any widget code.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterator

if TYPE_CHECKING:
    from .app import InkmillApp

Handler = Callable[["InkmillApp"], Any]
Predicate = Callable[["InkmillApp"], bool]


@dataclass
class Command:
    id: str
    label: str
    handler: Handler
    keys: tuple[str, ...] = ()
    description: str = ""
    # When False the command's keys are inactive while a dialog is open.
    global_: bool = False
    enabled: Predicate | None = None
    # Shown in the command palette; set False for internal plumbing.
    palette: bool = True
    tags: tuple[str, ...] = field(default_factory=tuple)

    def is_enabled(self, app: "InkmillApp") -> bool:
        if self.enabled is None:
            return True
        try:
            return bool(self.enabled(app))
        except Exception:
            return False

    async def run(self, app: "InkmillApp") -> Any:
        result = self.handler(app)
        if inspect.isawaitable(result):
            result = await result
        return result


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, command: Command, *, replace: bool = False) -> Command:
        if command.id in self._commands and not replace:
            raise ValueError(f"command {command.id!r} is already registered")
        self._commands[command.id] = command
        return command

    def add(
        self,
        id: str,
        label: str,
        keys: str | tuple[str, ...] = (),
        **kwargs: Any,
    ) -> Callable[[Handler], Handler]:
        """Decorator form: ``@registry.add("file.save", "Save", "ctrl+s")``."""

        if isinstance(keys, str):
            keys = tuple(k.strip() for k in keys.split(",") if k.strip())

        def decorator(func: Handler) -> Handler:
            self.register(Command(id=id, label=label, handler=func, keys=keys, **kwargs))
            return func

        return decorator

    def get(self, id: str) -> Command | None:
        return self._commands.get(id)

    def __contains__(self, id: object) -> bool:
        return id in self._commands

    def __iter__(self) -> Iterator[Command]:
        return iter(self._commands.values())

    def __len__(self) -> int:
        return len(self._commands)

    def apply_key_overrides(self, overrides: dict[str, str]) -> list[str]:
        """Apply user key overrides. Returns ids that matched no command."""
        unknown = []
        for cmd_id, keys in overrides.items():
            command = self._commands.get(cmd_id)
            if command is None:
                unknown.append(cmd_id)
                continue
            command.keys = tuple(k.strip() for k in keys.split(",") if k.strip())
        return unknown

    def key_conflicts(self) -> dict[str, list[str]]:
        seen: dict[str, list[str]] = {}
        for command in self:
            for key in command.keys:
                seen.setdefault(key, []).append(command.id)
        return {k: v for k, v in seen.items() if len(v) > 1}


def format_key(key: str) -> str:
    """Render a Textual key name the way a menu shows it: ``ctrl+s`` -> ``^S``."""
    parts = key.split("+")
    base = parts[-1]
    named = {
        "escape": "Esc",
        "pageup": "PgUp",
        "pagedown": "PgDn",
        "equals_sign": "=",
        "left_square_bracket": "[",
        "right_square_bracket": "]",
        "delete": "Del",
    }
    base = named.get(base, base.upper() if len(base) == 1 else base.capitalize())
    mods = parts[:-1]
    if mods == ["ctrl"] and len(base) == 1:
        return f"^{base}"
    prefix = "".join(f"{m.capitalize()}+" for m in mods)
    return prefix + base
