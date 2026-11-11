# Themes

More screen themes, a gallery that previews them on your own document as
you move through the list, and themes of your own written as small TOML
files. No Python needed.

## Commands

In the View menu:

| Command | What it does |
|---------|--------------|
| Theme Gallery... | Every theme, grouped by where it comes from. The screen changes as you move; Enter keeps it, Esc puts the old one back, N starts a new theme from the highlighted one. |
| New Theme from Current... | Writes a complete theme file based on the current theme and opens it. Each save applies it. |
| Reload Theme Files | Re-reads every theme file, for edits made in another editor. |
| Open Themes Folder | Opens the folder your theme files live in. |

## Bundled themes

| Theme | Inspired by |
|-------|-------------|
| Turbo | Early-1990s DOS programming editors: yellow on blue, gray menus, green highlight |
| Commander | Two-panel DOS file managers: cyan on blue with a cyan menu bar |
| DOS Mono | Monochrome text-mode word processors: gray on black, inverse menus |
| Eight-Bit | 1980s home computers: light blue on dark blue, block cursor |
| Focus | Minimal writing apps: near-black on off-white, a blue cursor and nothing else in color |
| Focus Night | The dark mode of the same: soft gray on charcoal |
| Sepia | The sepia page of e-readers: brown ink on warm paper |
| Midnight | Full-screen composition modes: warm text on a near-black page |
| E-Ink | E-paper tablets running Termux: pure black and white, nothing to ghost |
| High Contrast | System high-contrast modes: white on black, yellow highlights |

Inkmill's own themes (WordPerfect, Grinder, Paper, Amber, Phosphor) and the
themes that come with Textual (Nord, Gruvbox, Dracula, Solarized, Tokyo
Night, Catppuccin, Rose Pine and more) appear in the gallery too. Inkmill
works out menu, dialog and status colors for the Textual ones from their own
palettes.

## Writing a theme

Theme files go in the `themes` folder beside settings.toml (`inkmill
--paths` shows the config folder). Four colors are enough:

```toml
name = "harbor"            # lowercase letters, digits and dashes
dark = true
background = "#10202a"
foreground = "#d8e2e6"
primary = "#4fb3bf"        # menu highlight, selection, dialog borders
```

Everything else is optional:

```toml
label = "Harbor"                     # the name shown in the gallery
inspired_by = "Night on the water"   # shown under the list
accent = "#f2c14e"                   # headings and list markers

[ui]                                 # any of these; the rest are worked out
menu_bg = "#1b3340"
menu_fg = "#d8e2e6"
menu_hl_bg = "#4fb3bf"
menu_hl_fg = "#10202a"
menu_key = "#f2c14e"                 # the underlined letter in menus
status_bg = "#10202a"
status_fg = "#6f8a96"
select_bg = "#4fb3bf"
select_fg = "#10202a"
cursor_bg = "#f2c14e"
cursor_fg = "#10202a"
dialog_bg = "#1b3340"
dialog_fg = "#d8e2e6"
dialog_border = "#4fb3bf"
input_bg = "#0a161d"
input_fg = "#ffffff"
dim = "#6f8a96"                      # Markdown punctuation, secondary text
heading = "#f2c14e"
mark = "#f2c14e"                     # list markers, links, code
bold = "#ffffff"                     # bold text (Inkmill 0.5.1 and later)
italic = "#9fd8df"                   # italic text (Inkmill 0.5.1 and later)
```

The quickest way to start is New Theme from Current, which writes every key
with the current theme's values. Edit a color, press Ctrl+S, and the screen
changes. A file with a mistake is not applied, and the notice names the
file and the problem.

To share a theme, send the `.toml` file. To ship one with this plugin, add
it to `plugins/themes/themes/` in the Inkmill repository, bump the plugin
version and rebuild the index.

## Settings

The chosen theme is saved as `theme` in settings.toml, as with View >
Screen Theme.
