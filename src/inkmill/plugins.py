"""Plugin loading and the API plugins program against.

A plugin is any Python module exposing ``register(api: PluginAPI)``. Inkmill
finds plugins in three places:

* folders in ``<config dir>/plugins/`` holding a ``plugin.toml`` manifest and
  an ``__init__.py`` (the form the plugin manager installs),
* single ``*.py`` files in the same folder, and
* installed packages that declare an entry point in the ``inkmill.plugins``
  group.

A manifest names the plugin's version and the Inkmill versions it supports.
A plugin whose ``requires_inkmill`` does not match the running version is not
loaded, and the reason is shown instead.

Everything a plugin can do goes through :class:`PluginAPI`, which keeps the
surface small and stable while the internals move.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import sys
import tomllib
import traceback
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from textual.theme import Theme

from . import __version__
from .commands import Command, Handler
from .config import config_dir
from .export import Exporter
from .formats import DocumentFormat
from .menus import Menu, MenuItem, Separator

if TYPE_CHECKING:
    from .app import InkmillApp

log = logging.getLogger("inkmill.plugins")

ENTRY_POINT_GROUP = "inkmill.plugins"
MANIFEST = "plugin.toml"
# Module name prefixes for plugins loaded from files. A restart removes every
# module under these prefixes so the next load reads fresh code.
MODULE_PREFIXES = ("inkmill_plugin_", "inkmill_user_plugin_")

# Events the app emits. Handlers receive the arguments listed.
EVENTS = {
    "ready": (),  # the app has finished starting
    "document_opened": ("doc",),
    "document_activated": ("doc",),
    "document_saved": ("doc",),
    "document_closed": ("doc",),
    "document_reloaded": ("doc",),
    "file_moved": ("old", "new"),
    "file_deleted": ("path",),
}


def plugins_dir() -> Path:
    return config_dir() / "plugins"


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    requires_inkmill: str = ""
    summary: str = ""
    author: str = ""
    license: str = ""
    homepage: str = ""
    external: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any], fallback_id: str = "") -> "Manifest":
        external = data.get("external", [])
        return cls(
            id=str(data.get("id") or fallback_id),
            name=str(data.get("name") or data.get("id") or fallback_id),
            version=str(data.get("version", "0")),
            requires_inkmill=str(data.get("requires_inkmill", "")),
            summary=str(data.get("summary", "")),
            author=str(data.get("author", "")),
            license=str(data.get("license", "")),
            homepage=str(data.get("homepage", "")),
            external=[str(e) for e in external] if isinstance(external, list) else [],
        )

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data, path.parent.name)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "requires_inkmill": self.requires_inkmill,
            "summary": self.summary,
            "author": self.author,
            "license": self.license,
            "homepage": self.homepage,
            "external": list(self.external),
        }
        return {k: v for k, v in data.items() if v not in ("", [])}


def parse_version(text: str) -> Version | None:
    try:
        return Version(text)
    except InvalidVersion:
        return None


def is_compatible(requires: str, version: str = __version__) -> bool:
    """True when ``version`` satisfies a specifier such as ``>=0.2,<1``."""
    if not requires.strip():
        return True
    try:
        return SpecifierSet(requires).contains(version, prereleases=True)
    except InvalidSpecifier:
        return False


def describe_requirement(requires: str) -> str:
    """Human wording for a specifier, for example "Inkmill 0.3 or newer"."""
    requires = requires.strip()
    if requires.startswith(">=") and "," not in requires:
        return f"Inkmill {requires[2:].strip()} or newer"
    return f"Inkmill {requires}"


@dataclass
class PluginInfo:
    name: str
    source: str
    error: str | None = None
    manifest: Manifest | None = None
    # Why the plugin was not loaded, when it was skipped on purpose.
    skipped: str | None = None
    path: Path | None = None

    @property
    def version(self) -> str:
        return self.manifest.version if self.manifest else ""

    @property
    def loaded(self) -> bool:
        return self.error is None and self.skipped is None


class EventBus:
    """Named events with plugin-registered callbacks.

    A callback that returns an awaitable runs in a worker, so it may show
    dialogs. A callback that raises is logged and reported; it never stops
    the other callbacks or the app.
    """

    def __init__(self, app: "InkmillApp") -> None:
        self.app = app
        self._handlers: dict[str, list[Callable[..., Any]]] = {}

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        if event not in EVENTS:
            raise ValueError(f"unknown event {event!r}; known events: {', '.join(EVENTS)}")
        self._handlers.setdefault(event, []).append(callback)

    def emit(self, event: str, *args: Any) -> None:
        for callback in list(self._handlers.get(event, [])):
            try:
                result = callback(self.app, *args)
            except Exception as exc:
                log.exception("event handler for %s failed", event)
                self.app.notify(f"Plugin error in {event}: {exc}", severity="error", timeout=8)
                continue
            if inspect.isawaitable(result):
                self.app.run_worker(self._guard(event, result), group="plugin-event", exit_on_error=False)

    async def _guard(self, event: str, awaitable: Any) -> None:
        try:
            await awaitable
        except Exception as exc:
            log.exception("event handler for %s failed", event)
            self.app.notify(f"Plugin error in {event}: {exc}", severity="error", timeout=8)


class PluginAPI:
    """The interface handed to each plugin's ``register`` function."""

    def __init__(self, app: "InkmillApp", plugin_name: str, path: Path | None = None, manifest: Manifest | None = None) -> None:
        self.app = app
        self.plugin_name = plugin_name
        self.path = path
        self.manifest = manifest

    @property
    def inkmill_version(self) -> str:
        return __version__

    @property
    def settings(self) -> dict[str, Any]:
        """This plugin's own table from ``[plugins.<name>]`` in settings.toml."""
        return self.app.settings.plugins.setdefault(self.plugin_name, {})

    def save_settings(self) -> None:
        self.app.settings.save()

    def command(
        self,
        id: str,
        label: str,
        keys: str = "",
        *,
        menu: str | None = None,
        description: str = "",
        enabled: Callable[["InkmillApp"], bool] | None = None,
        separator: bool = False,
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
                self.add_menu_item(menu, id, separator=separator)
            return func

        return decorator

    def add_menu(self, id: str, label: str, *, before: str | None = "help") -> Menu:
        return self.app.menus.ensure(id, label, before=before)

    def add_menu_item(self, menu: str, command: str, *, label: str | None = None, after: str | None = None, separator: bool = False) -> None:
        target = self.app.menus.get(menu) or self.add_menu(menu, self.plugin_name.title())
        if separator:
            target.add(Separator(), after=after)
        target.add(MenuItem(command, label), after=after)

    def on(self, event: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator subscribing to an app event. See :data:`EVENTS`."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.app.events.on(event, func)
            return func

        return decorator

    def status_segment(self, func: Callable[["InkmillApp"], str | None]) -> Callable[["InkmillApp"], str | None]:
        """Register a function whose text is shown at the left of the status position.

        It is called whenever the status line is fully refreshed (switching
        documents, saving) and after :meth:`refresh_status`. Keep it cheap;
        compute anything slow elsewhere and cache it.
        """
        self.app.status_segments.append(func)
        return func

    def refresh_status(self) -> None:
        self.app.update_status(full=True)

    async def run_in_thread(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run blocking work (a subprocess, a file scan) off the UI thread."""
        return await asyncio.to_thread(func, *args, **kwargs)

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


def _load_package(directory: Path):
    name = f"inkmill_plugin_{directory.name}"
    init = directory / "__init__.py"
    spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[str(directory)])
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {directory}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


@dataclass
class Found:
    name: str
    source: str
    loader: Callable[[], Any]
    manifest: Manifest | None = None
    path: Path | None = None
    error: str | None = None


def discover(directory: Path | None = None) -> list[Found]:
    """Every plugin Inkmill can see, loaded or not."""
    found: list[Found] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        found.append(Found(ep.name, f"entry point {ep.value}", ep.load))
    plugin_dir = directory or plugins_dir()
    if plugin_dir.is_dir():
        for path in sorted(plugin_dir.iterdir(), key=lambda p: p.name):
            if path.name.startswith(("_", ".")):
                continue
            if path.is_dir() and (path / MANIFEST).is_file():
                try:
                    manifest = Manifest.load(path / MANIFEST)
                except (OSError, tomllib.TOMLDecodeError) as exc:
                    found.append(Found(path.name, str(path), lambda: None, path=path, error=f"bad {MANIFEST}: {exc}"))
                    continue
                if not (path / "__init__.py").is_file():
                    found.append(Found(manifest.id, str(path), lambda: None, manifest, path, error="no __init__.py"))
                    continue
                found.append(Found(manifest.id, str(path), lambda p=path: _load_package(p), manifest, path))
            elif path.is_file() and path.suffix == ".py":
                found.append(Found(path.stem, str(path), lambda p=path: _load_module_from_file(p), path=path))
    return found


def load_plugins(app: "InkmillApp", directory: Path | None = None) -> list[PluginInfo]:
    infos: list[PluginInfo] = []
    disabled = set(app.settings.plugins.get("disabled", []) or [])
    for item in discover(directory):
        info = PluginInfo(item.name, item.source, manifest=item.manifest, path=item.path)
        infos.append(info)
        if item.name in disabled:
            info.skipped = "disabled"
            continue
        if item.error:
            info.error = item.error
            continue
        if item.manifest and not is_compatible(item.manifest.requires_inkmill):
            info.skipped = f"needs {describe_requirement(item.manifest.requires_inkmill)}"
            continue
        try:
            target = item.loader()
            register = getattr(target, "register", None) or (target if callable(target) else None)
            if register is None:
                raise AttributeError("plugin has no register(api) function")
            register(PluginAPI(app, item.name, item.path, item.manifest))
        except Exception:
            info.error = traceback.format_exc(limit=3)
    return infos


def purge_plugin_modules() -> None:
    """Forget every module loaded from a plugin file, so a restart reloads it."""
    for name in list(sys.modules):
        if name.startswith(MODULE_PREFIXES):
            del sys.modules[name]
