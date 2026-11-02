"""Plugin loading and the API plugins program against.

A plugin is any Python module exposing ``register(api: PluginAPI)``. Inkmill
finds plugins in two places:

* installed packages that declare an entry point in the ``inkmill.plugins``
  group, and
* ``*.py`` files in ``<config dir>/plugins/``.

Everything a plugin can do goes through :class:`PluginAPI`, which keeps the
surface small and stable while the internals move.
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from textual.theme import Theme

from .commands import Command, Handler
from .config import config_dir
from .export import Exporter
from .formats import DocumentFormat
from .menus import Menu, MenuItem, Separator

if TYPE_CHECKING:
    from .app import InkmillApp

ENTRY_POINT_GROUP = "inkmill.plugins"


@dataclass
class PluginInfo:
    name: str
    source: str
    error: str | None = None


class PluginAPI:
    """The interface handed to each plugin's ``register`` function."""

    def __init__(self, app: "InkmillApp", plugin_name: str) -> None:
        self.app = app
        self.plugin_name = plugin_name

    @property
    def settings(self) -> dict[str, Any]:
        """This plugin's own table from ``[plugins.<name>]`` in settings.toml."""
        return self.app.settings.plugins.setdefault(self.plugin_name, {})

    def command(
        self,
        id: str,
        label: str,
        keys: str = "",
        *,
        menu: str | None = None,
        description: str = "",
        enabled: Callable[["InkmillApp"], bool] | None = None,
    ) -> Callable[[Handler], Handler]:
        """Decorator registering a command, optionally adding it to a menu.

        ``menu`` is a menu id such as ``"format"`` or a new id, which creates
        a menu titled after the plugin.
        """

        def decorator(func: Handler) -> Handler:
            self.app.commands.register(
                Command(
                    id=id,
                    label=label,
                    handler=func,
                    keys=tuple(k.strip() for k in keys.split(",") if k.strip()),
                    description=description,
                    enabled=enabled,
                )
            )
            if menu:
                self.add_menu_item(menu, id)
            return func

        return decorator

    def add_menu(self, id: str, label: str, *, before: str | None = "help") -> Menu:
        return self.app.menus.ensure(id, label, before=before)

    def add_menu_item(self, menu: str, command: str, *, label: str | None = None, after: str | None = None, separator: bool = False) -> None:
        target = self.app.menus.get(menu) or self.add_menu(menu, self.plugin_name.title())
        if separator:
            target.add(Separator(), after=after)
        target.add(MenuItem(command, label), after=after)

    def register_format(self, fmt: DocumentFormat) -> None:
        self.app.formats.register(fmt)

    def register_exporter(self, exporter: Exporter) -> None:
        self.app.exporters.register(exporter)

    def register_theme(self, theme: Theme) -> None:
        self.app.register_theme(theme)

    @property
    def editor(self):
        """The active :class:`~inkmill.widgets.editor.InkEditor`, or None."""
        return self.app.active_editor


def _load_module_from_file(path: Path):
    name = f"inkmill_user_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def discover(directory: Path | None = None) -> list[tuple[str, str, Callable[[], Any]]]:
    """Return (name, source, loader) for every plugin found."""
    found: list[tuple[str, str, Callable[[], Any]]] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        found.append((ep.name, f"entry point {ep.value}", ep.load))
    plugin_dir = directory or (config_dir() / "plugins")
    if plugin_dir.is_dir():
        for path in sorted(plugin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            found.append((path.stem, str(path), lambda p=path: _load_module_from_file(p)))
    return found


def load_plugins(app: "InkmillApp", directory: Path | None = None) -> list[PluginInfo]:
    infos: list[PluginInfo] = []
    disabled = set(app.settings.plugins.get("disabled", []) or [])
    for name, source, loader in discover(directory):
        if name in disabled:
            continue
        info = PluginInfo(name, source)
        try:
            target = loader()
            register = getattr(target, "register", None) or (target if callable(target) else None)
            if register is None:
                raise AttributeError("plugin has no register(api) function")
            register(PluginAPI(app, name))
        except Exception:
            info.error = traceback.format_exc(limit=3)
        infos.append(info)
    return infos
