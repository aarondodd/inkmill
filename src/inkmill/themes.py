"""Screen themes.

Each Inkmill theme is a Textual :class:`~textual.theme.Theme` plus a set of
``im-*`` variables the stylesheet uses for the menu bar, dropdowns, status bar
and file manager. Any Textual theme also works: missing ``im-*`` values fall
back to :data:`VARIABLE_DEFAULTS`, which derive from the theme's own palette.
"""

from __future__ import annotations

from rich.style import Style
from textual.theme import Theme
from textual.widgets.text_area import TextAreaTheme

# Fallbacks for themes that do not define Inkmill's variables.
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


def _theme(name: str, *, dark: bool, background: str, foreground: str, primary: str, **im: str) -> Theme:
    variables = {f"im-{k.replace('_', '-')}": v for k, v in im.items()}
    variables.setdefault("block-cursor-background", variables.get("im-cursor-bg", foreground))
    variables.setdefault("block-cursor-foreground", variables.get("im-cursor-fg", background))
    variables.setdefault("block-cursor-text-style", "none")
    variables.setdefault("input-selection-background", variables.get("im-select-bg", primary) + " 60%")
    return Theme(
        name=name,
        primary=primary,
        secondary=primary,
        accent=variables.get("im-heading", primary),
        foreground=foreground,
        background=background,
        surface=background,
        panel=variables.get("im-menu-bg", background),
        warning="#ffff55",
        error="#ff5555",
        success="#55ff55",
        dark=dark,
        variables=variables,
    )


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


def syntax_theme(theme: Theme) -> TextAreaTheme:
    """Markdown highlighting colors for the editor, derived from a screen theme.

    Only syntax colors are set; the background, cursor and selection keep
    following the stylesheet, so they always match the screen theme.
    """
    v = {**VARIABLE_DEFAULTS, **theme.variables}
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
        },
    )
