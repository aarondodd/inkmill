"""Theme files: TOML in, Textual themes out.

A theme file needs only four keys::

    name = "harbor"          # lowercase letters, digits and dashes
    dark = true
    background = "#10202a"
    foreground = "#d8e2e6"
    primary = "#4fb3bf"      # menu highlight, selection, dialog borders

Everything else is optional: ``label`` and ``inspired_by`` are shown in the
gallery, ``accent`` colors headings, and a ``[ui]`` table overrides any of
Inkmill's interface colors (``menu_bg``, ``status_fg``, ``cursor_bg`` and the
rest of :data:`inkmill.themes.UI_KEYS`, with underscores). Whatever is left out
is worked out from the four base colors.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from textual.theme import Theme

from inkmill.themes import UI_KEYS, derive_variables, make_theme

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
REQUIRED = ("name", "background", "foreground", "primary")


class ThemeFileError(Exception):
    pass


@dataclass
class ThemeInfo:
    theme: Theme
    label: str
    inspired_by: str
    source: str  # "inkmill", "bundled", "yours", "textual"
    path: Path | None = None


def parse(data: dict, origin: str) -> tuple[Theme, str, str]:
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise ThemeFileError(f"{origin}: missing {', '.join(missing)}")
    name = str(data["name"])
    if not NAME.match(name):
        raise ThemeFileError(f"{origin}: name {name!r} must be lowercase letters, digits and dashes")
    ui = data.get("ui", {})
    if not isinstance(ui, dict):
        raise ThemeFileError(f"{origin}: [ui] must be a table")
    try:
        theme = make_theme(
            name,
            dark=bool(data.get("dark", True)),
            background=str(data["background"]),
            foreground=str(data["foreground"]),
            primary=str(data["primary"]),
            accent=str(data["accent"]) if data.get("accent") else None,
            **{str(k): str(v) for k, v in ui.items()},
        )
    except ValueError as exc:
        raise ThemeFileError(f"{origin}: {exc}") from exc
    label = str(data.get("label") or name.replace("-", " ").title())
    return theme, label, str(data.get("inspired_by", ""))


def load_file(path: Path, source: str) -> ThemeInfo:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ThemeFileError(f"{path.name}: {exc.strerror or exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ThemeFileError(f"{path.name}: {exc}") from exc
    theme, label, inspired = parse(data, path.name)
    return ThemeInfo(theme, label, inspired, source, path)


def load_folder(folder: Path, source: str) -> tuple[list[ThemeInfo], list[str]]:
    themes: list[ThemeInfo] = []
    errors: list[str] = []
    if not folder.is_dir():
        return themes, errors
    for path in sorted(folder.glob("*.toml"), key=lambda p: p.name):
        try:
            themes.append(load_file(path, source))
        except ThemeFileError as exc:
            errors.append(str(exc))
    return themes, errors


def to_toml(theme: Theme, name: str, label: str, based_on: str) -> str:
    """A complete, editable theme file reproducing ``theme`` under a new name."""
    variables = {**derive_variables(theme), **theme.variables}
    lines = [
        f"# Based on the {based_on} theme. Save this file to apply your changes.",
        "# Colors are #rrggbb. Remove any [ui] line to have it worked out from",
        "# the base colors instead.",
        f'name = "{name}"',
        f'label = "{label}"',
        'inspired_by = ""',
        f"dark = {'true' if theme.dark else 'false'}",
        f'background = "{_hex(theme.background)}"',
        f'foreground = "{_hex(theme.foreground)}"',
        f'primary = "{_hex(theme.primary)}"',
        "",
        "[ui]",
    ]
    for key in UI_KEYS:
        value = variables.get(f"im-{key}")
        if value:
            lines.append(f'{key.replace("-", "_")} = "{_hex(value)}"')
    return "\n".join(lines) + "\n"


def _hex(value: str | None) -> str:
    from textual.color import Color

    if not value:
        return "#000000"
    try:
        return Color.parse(value).hex6.lower()
    except Exception:
        return str(value)
