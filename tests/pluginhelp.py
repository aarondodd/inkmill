"""Helpers for tests that load plugins from the repository's plugins folder."""

import importlib.util
import sys
from pathlib import Path

from inkmill.app import InkmillApp
from inkmill.config import Settings, State

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"
ALL = sorted(p.name for p in PLUGINS.iterdir() if (p / "plugin.toml").is_file())


def app_with(tmp_path, *enabled, paths=(), **settings):
    """An app loading only the named repository plugins."""
    plugins = dict(settings.pop("plugins", {}))
    plugins["disabled"] = [p for p in ALL if p not in enabled]
    settings.setdefault("restore_session", False)
    settings.setdefault("recovery_interval", 0)
    return InkmillApp(paths, settings=Settings(plugins=plugins, **settings), state=State(tmp_path / "state.json"), plugin_dir=PLUGINS)


def load_module(plugin: str, module: str):
    """Import plugins/<plugin>/<module>.py directly, for unit tests."""
    name = f"_test_{plugin}_{module}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PLUGINS / plugin / f"{module}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


async def wait_for(pilot, predicate, timeout=5.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        await pilot.pause(0.05)
    return predicate()
