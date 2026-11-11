"""Screen themes.

Each Inkmill theme is a Textual :class:`~textual.theme.Theme` plus a set of
``im-*`` variables the stylesheet uses for the menu bar, dropdowns, status bar
and file manager. Any Textual theme also works: :func:`derive_variables`
works out every missing ``im-*`` value from the theme's own palette, so
Nord, Dracula and the rest get menus and dialogs in their own colors.
"""

from __future__ import annotations

from rich.style import Style
from textual.color import Color
from textual.theme import Theme
from textual.widgets.text_area import TextAreaTheme

# The names of Inkmill's own variables, without the "im-" prefix. Theme files
# and make_theme() use these with underscores (menu_bg).
UI_KEYS = (
    "menu-bg", "menu-fg", "menu-hl-bg", "menu-hl-fg", "menu-key",
    "status-bg", "status-fg", "select-bg", "select-fg", "cursor-bg", "cursor-fg",
    "dialog-bg", "dialog-fg", "dialog-border", "input-bg", "input-fg",
    "dim", "heading", "mark",
)

# WordPerfect values, used only if a theme's palette cannot be read at all.
VARIABLE_DEFAULTS: dict[str, str] = {
    "im-menu-bg": "#aaaaaa",
    "im-menu-fg": "#000000",
    "im-menu-hl-bg": "#000000",
    "im-menu-hl-fg": "#ffffff",
    "im-menu-key": "#aa0000",
    "im-status-bg": "#0000aa",
    "im-status-fg": "#ffffff",
    "im-select-bg": "#aaaaaa",
    "im-select-fg": "#0000aa",
    "im-cursor-bg": "#ffffff",
    "im-cursor-fg": "#0000aa",
    "im-dialog-bg": "#aaaaaa",
    "im-dialog-fg": "#000000",
    "im-dialog-border": "#ffffff",
    "im-input-bg": "#0000aa",
    "im-input-fg": "#ffffff",
    "im-dim": "#aaaaaa",
    "im-heading": "#ffff55",
    "im-mark": "#ffff55",
}


def _contrast(color: Color) -> str:
    return "#000000" if color.brightness > 0.55 else "#ffffff"


def _distinct(color: Color, against: Color, fallback: Color) -> Color:
    """``color`` unless it is too close to ``against`` to read, else ``fallback``."""
    return color if abs(color.brightness - against.brightness) > 0.18 else fallback


def derive_variables(theme: Theme) -> dict[str, str]:
    """Every ``im-*`` variable, worked out from a theme's base colors."""
    try:
        system = theme.to_color_system().generate()
        bg = Color.parse(system["background"])
        fg = Color.parse(theme.foreground or system["foreground"])
        primary = Color.parse(system["primary"])
        accent = Color.parse(theme.accent or system["primary"])
        panel = Color.parse(theme.panel or system["panel"])
    except Exception:
        return dict(VARIABLE_DEFAULTS)
    if abs(panel.brightness - bg.brightness) < 0.04:
        panel = bg.lighten(0.12) if theme.dark else bg.darken(0.08)
    dim = fg.blend(bg, 0.45)
    heading = _distinct(accent, bg, fg)
    return {
        "im-menu-bg": panel.hex,
        "im-menu-fg": fg.hex,
        "im-menu-hl-bg": primary.hex,
        "im-menu-hl-fg": _contrast(primary),
        "im-menu-key": _distinct(accent, panel, primary).hex,
        "im-status-bg": bg.hex,
        "im-status-fg": dim.hex,
        "im-select-bg": primary.hex,
        "im-select-fg": _contrast(primary),
        "im-cursor-bg": fg.hex,
        "im-cursor-fg": bg.hex,
        "im-dialog-bg": panel.hex,
        "im-dialog-fg": fg.hex,
        "im-dialog-border": primary.hex,
        "im-input-bg": bg.hex,
        "im-input-fg": fg.hex,
        "im-dim": dim.hex,
        "im-heading": heading.hex,
        "im-mark": heading.hex,
    }


def make_theme(
    name: str,
    *,
    dark: bool,
    background: str,
    foreground: str,
    primary: str,
    accent: str | None = None,
    **ui: str,
) -> Theme:
    """Build an Inkmill theme from four colors plus any ``im-*`` overrides.

    ``ui`` keys are the names in :data:`UI_KEYS` with underscores, such as
    ``menu_bg``. Anything left out is derived, so a theme can be as small as
    a background, a foreground and a highlight color.
    """
    unknown = [k for k in ui if k.replace("_", "-") not in UI_KEYS]
    if unknown:
        raise ValueError(f"unknown theme keys: {', '.join(sorted(unknown))}")
    for value in (background, foreground, primary, accent, *ui.values()):
        if value is not None:
            try:
                Color.parse(value)
            except Exception as exc:  # ColorParseError is not a ValueError
                raise ValueError(f"{value!r} is not a color; use #rrggbb") from exc
    explicit = {f"im-{k.replace('_', '-')}": v for k, v in ui.items()}
    base = Theme(
        name=name,
        primary=primary,
        accent=accent or explicit.get("im-heading") or primary,
        foreground=foreground,
        background=background,
        surface=background,
        panel=explicit.get("im-menu-bg"),
        dark=dark,
    )
    variables = {**derive_variables(base), **explicit}
    variables["block-cursor-background"] = variables["im-cursor-bg"]
    variables["block-cursor-foreground"] = variables["im-cursor-fg"]
    variables["block-cursor-text-style"] = "none"
    variables["input-selection-background"] = variables["im-select-bg"] + " 60%"
    return Theme(
        name=name,
        primary=primary,
        secondary=primary,
        accent=variables["im-heading"],
        foreground=foreground,
        background=background,
        surface=background,
        panel=variables["im-menu-bg"],
        warning="#ffff55" if dark else "#9a6700",
        error="#ff5555" if dark else "#c62828",
        success="#55ff55" if dark else "#2e7d32",
        dark=dark,
        variables=variables,
    )


_theme = make_theme


# WordPerfect 5.1 for DOS: CGA blue, white text, gray pull-down menus.
WORDPERFECT = _theme(
    "wordperfect",
    dark=True,
    background="#0000aa",
    foreground="#ffffff",
    primary="#55ffff",
    menu_bg="#aaaaaa",
    menu_fg="#000000",
    menu_hl_bg="#000000",
    menu_hl_fg="#ffffff",
    menu_key="#aa0000",
    status_bg="#0000aa",
    status_fg="#ffffff",
    select_bg="#aaaaaa",
    select_fg="#0000aa",
    cursor_bg="#ffffff",
    cursor_fg="#0000aa",
    dialog_bg="#aaaaaa",
    dialog_fg="#000000",
    dialog_border="#ffffff",
    input_bg="#0000aa",
    input_fg="#ffffff",
    dim="#aaaaaa",
    heading="#ffff55",
    mark="#ffff55",
)

# WordGrinder's default look: light text on black with cyan accents.
GRINDER = _theme(
    "grinder",
    dark=True,
    background="#000000",
    foreground="#c0c0c0",
    primary="#00aaaa",
    menu_bg="#00aaaa",
    menu_fg="#000000",
    menu_hl_bg="#ffffff",
    menu_hl_fg="#000000",
    menu_key="#ffffff",
    status_bg="#000000",
    status_fg="#00aaaa",
    select_bg="#c0c0c0",
    select_fg="#000000",
    cursor_bg="#c0c0c0",
    cursor_fg="#000000",
    dialog_bg="#00aaaa",
    dialog_fg="#000000",
    dialog_border="#ffffff",
    input_bg="#000000",
    input_fg="#ffffff",
    dim="#808080",
    heading="#ffffff",
    mark="#00ffff",
)

PAPER = _theme(
    "paper",
    dark=False,
    background="#f7f3e8",
    foreground="#2b2b2b",
    primary="#8b2e16",
    menu_bg="#e4ddca",
    menu_fg="#2b2b2b",
    menu_hl_bg="#8b2e16",
    menu_hl_fg="#ffffff",
    menu_key="#8b2e16",
    status_bg="#e4ddca",
    status_fg="#2b2b2b",
    select_bg="#d9c9a3",
    select_fg="#2b2b2b",
    cursor_bg="#2b2b2b",
    cursor_fg="#f7f3e8",
    dialog_bg="#ece6d6",
    dialog_fg="#2b2b2b",
    dialog_border="#8b2e16",
    input_bg="#ffffff",
    input_fg="#2b2b2b",
    dim="#8a8170",
    heading="#8b2e16",
    mark="#8b2e16",
)

AMBER = _theme(
    "amber",
    dark=True,
    background="#1a1000",
    foreground="#ffb000",
    primary="#ffcc00",
    menu_bg="#ffb000",
    menu_fg="#1a1000",
    menu_hl_bg="#1a1000",
    menu_hl_fg="#ffcc00",
    menu_key="#7a3d00",
    status_bg="#1a1000",
    status_fg="#cc8800",
    select_bg="#ffb000",
    select_fg="#1a1000",
    cursor_bg="#ffcc00",
    cursor_fg="#1a1000",
    dialog_bg="#2a1a00",
    dialog_fg="#ffb000",
    dialog_border="#ffb000",
    input_bg="#1a1000",
    input_fg="#ffcc00",
    dim="#996600",
    heading="#ffdd55",
    mark="#ffdd55",
)

PHOSPHOR = _theme(
    "phosphor",
    dark=True,
    background="#001100",
    foreground="#33ff66",
    primary="#66ff99",
    menu_bg="#33ff66",
    menu_fg="#001100",
    menu_hl_bg="#001100",
    menu_hl_fg="#66ff99",
    menu_key="#005511",
    status_bg="#001100",
    status_fg="#22aa44",
    select_bg="#33ff66",
    select_fg="#001100",
    cursor_bg="#66ff99",
    cursor_fg="#001100",
    dialog_bg="#002200",
    dialog_fg="#33ff66",
    dialog_border="#33ff66",
    input_bg="#001100",
    input_fg="#66ff99",
    dim="#1f8f3f",
    heading="#aaffcc",
    mark="#aaffcc",
)

BUILTIN_THEMES: tuple[Theme, ...] = (WORDPERFECT, GRINDER, PAPER, AMBER, PHOSPHOR)


def syntax_theme(theme: Theme, decorations: dict | None = None) -> TextAreaTheme:
    """Markdown highlighting colors for the editor, derived from a screen theme.

    Only syntax colors are set; the background, cursor and selection keep
    following the stylesheet, so they always match the screen theme.
    """
    v = {**derive_variables(theme), **theme.variables}
    extra: dict[str, Style] = {}
    for name, style in (decorations or {}).items():
        try:
            extra[name] = style(v) if callable(style) else style
        except Exception:
            continue
    heading = v["im-heading"]
    dim = v["im-dim"]
    mark = v["im-mark"]
    return TextAreaTheme(
        name="inkmill",
        syntax_styles={
            "heading": Style(color=heading, bold=True),
            "heading.marker": Style(color=dim),
            "list.marker": Style(color=mark),
            "link.label": Style(color=mark, underline=True),
            "link.uri": Style(color=dim),
            "text.literal": Style(color=mark),
            "punctuation.delimiter": Style(color=dim),
            "punctuation.special": Style(color=dim),
            "string.escape": Style(color=dim),
            # Rich view (inkmill.richtext): formatting over the source text.
            "rich.marker": Style(color=dim, bold=False, italic=False, underline=False, strike=False),
            "rich.bold": Style(bold=True),
            "rich.italic": Style(italic=True),
            "rich.bold_italic": Style(bold=True, italic=True),
            "rich.strike": Style(strike=True),
            "rich.highlight": Style(reverse=True),
            "rich.code": Style(color=mark),
            "rich.h1": Style(color=heading, bold=True, underline=True),
            "rich.heading": Style(color=heading, bold=True),
            "rich.link": Style(color=mark, underline=True),
            "rich.url": Style(color=dim),
            "rich.footnote": Style(color=mark),
            "rich.quote": Style(italic=True),
            "rich.list": Style(color=mark, bold=True),
            "rich.done": Style(color=dim, strike=True),
            "rich.table_header": Style(bold=True),
            "rich.frontmatter": Style(color=dim),
            **extra,
        },
    )
