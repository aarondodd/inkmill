"""User settings and persistent state.

Settings live in ``settings.toml`` under the platform config directory and are
meant to be hand-editable. Volatile state (recent files, the last session, crash
recovery snapshots) lives under the platform state directory as JSON.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import platformdirs
import tomli_w

APP_DIR_NAME = "inkmill"
MAX_RECENT = 15


def config_dir() -> Path:
    override = os.environ.get("INKMILL_CONFIG_DIR")
    return Path(override) if override else Path(platformdirs.user_config_dir(APP_DIR_NAME, appauthor=False))


def state_dir() -> Path:
    override = os.environ.get("INKMILL_STATE_DIR")
    return Path(override) if override else Path(platformdirs.user_state_dir(APP_DIR_NAME, appauthor=False))


@dataclass
class Settings:
    """Everything a user can tune. Unknown keys in the file are preserved."""

    theme: str = "wordperfect"
    # "auto" shows the menu bar only while a menu is open; "always" pins it.
    menu_bar: str = "auto"
    status_bar: bool = True
    # Width of the writing column in characters; 0 uses the full terminal width.
    page_width: int = 80
    soft_wrap: bool = True
    lines_per_page: int = 54
    syntax_highlight: bool = True
    default_format: str = "markdown"
    export_style: str = "classic"
    typographer: bool = True
    restore_session: bool = True
    # Seconds between crash-recovery snapshots of unsaved documents; 0 disables.
    recovery_interval: int = 30
    # Command id to key string overrides, for example {"file.save" = "ctrl+s,f10"}.
    keys: dict[str, str] = field(default_factory=dict)
    # Free-form per-plugin settings, keyed by plugin name.
    plugins: dict[str, Any] = field(default_factory=dict)
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "settings.toml"

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or cls.path()
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                data = {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        known = {f.name for f in fields(cls) if not f.name.startswith("_")}
        defaults = cls()
        kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for key, value in data.items():
            if key in known:
                expected = type(getattr(defaults, key))
                if expected is bool and not isinstance(value, bool):
                    continue
                if expected is int and (isinstance(value, bool) or not isinstance(value, int)):
                    continue
                if expected in (str, dict) and not isinstance(value, expected):
                    continue
                kwargs[key] = value
            else:
                extra[key] = value
        settings = cls(**kwargs)
        settings._extra = extra
        return settings

    def to_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        data.update(self._extra)
        return data

    def save(self, path: Path | None = None) -> None:
        path = path or self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(tomli_w.dumps(self.to_dict()), encoding="utf-8")
        tmp.replace(path)


class State:
    """Small JSON-backed store for recent files and the last session."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (state_dir() / "state.json")
        self.data: dict[str, Any] = {"recent": [], "session": []}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except (OSError, ValueError):
                pass

    @property
    def recent(self) -> list[str]:
        return [p for p in self.data.get("recent", []) if isinstance(p, str)]

    def add_recent(self, path: Path) -> None:
        resolved = str(Path(path).resolve())
        recent = [p for p in self.recent if p != resolved]
        recent.insert(0, resolved)
        self.data["recent"] = recent[:MAX_RECENT]

    @property
    def session(self) -> list[str]:
        return [p for p in self.data.get("session", []) if isinstance(p, str)]

    @session.setter
    def session(self, paths: list[str]) -> None:
        self.data["session"] = list(paths)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass
