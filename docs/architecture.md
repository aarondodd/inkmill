# Architecture

Inkmill is a [Textual](https://textual.textualize.io/) application. The code
separates the parts that change for different reasons: the registries that
describe what the app can do, the documents it holds, and the widgets that
draw it.

```
src/inkmill/
  app.py            InkmillApp: registries, open documents, key dispatch, status
  builtin.py        every built-in command and the default menu layout
  commands.py       Command and CommandRegistry
  menus.py          Menu, MenuItem, Separator, MenuModel
  documents.py      Document, DocumentList, word counting
  formats/          DocumentFormat registry (Markdown, plain text)
  export/           Exporter registry, Markdown parser, HTML export, CSS styles
  markup.py         pure Markdown editing helpers (headings, lists, tables)
  plugins.py        plugin discovery and PluginAPI
  recovery.py       crash recovery snapshots
  config.py         settings.toml and state.json
  system.py         platform detection and opening the browser
  themes.py         screen themes and editor syntax colors
  widgets/          InkEditor, MenuStrip and MenuScreen, StatusBar
  screens/          dialogs and the List Files screen
```

## Commands are the spine

Every action is a `Command` in one `CommandRegistry`: an id, a label, default
keys, an optional `enabled` predicate and a handler taking the app. Three
views read the registry:

- Key bindings. `InkmillApp._bind_command_keys` binds each command's keys as
  priority bindings to `action_command(id)`. `check_action` disables them
  while a dialog or the menu is open, so Ctrl+C in a text field still copies
  and Ctrl+N cannot open a document behind a dialog.
- Menus. `MenuModel` holds menus whose items reference command ids. The menu
  screen looks up labels, keys and enabled state at the moment it opens.
- The command palette. `get_system_commands` lists every enabled command.

User key overrides and plugin commands enter the same registry before keys
are bound, so all three views stay consistent without extra wiring.

Handlers run in a Textual worker, which is what lets an `async` handler call
`push_screen_wait` and await a dialog. A handler that raises produces an error
notice; it never takes the session down with it.

## Documents and editors

`Document` holds the text, its path, its format and the text as last saved;
`dirty` compares the two. Each open document gets its own `InkEditor` inside a
`ContentSwitcher`, so undo history, cursor and scroll position stay with the
document when you switch away. The editor writes its text back to the document
on every change; the word count in the status line is debounced.

Opening a file replaces the empty untitled document Inkmill starts with, so
the common "start Inkmill, open a file" path does not leave a stray Untitled
behind.

## Formats and export

A `DocumentFormat` maps file extensions to a loader and saver. The editor only
ever sees text, so a richer format converts at the boundary.

The HTML exporter parses Markdown with markdown-it-py in GFM mode plus
footnotes, definition lists, front matter and heading anchors
(`export/markdown.py`), then wraps the body in a standalone page with the
chosen style sheet inlined (`export/html.py`). Style sheets are bundled CSS
files layered over `_base.css`, and the user's styles folder can add or
replace them.

## Platform notes

- Every runtime dependency is pure Python, which is what makes Termux work.
  Editor highlighting needs tree-sitter and is an optional extra; without it
  the editor shows plain text.
- `system.open_in_browser` uses `webbrowser` on desktops, `wslview` or
  `explorer.exe` under WSL, and a loopback HTTP server plus `termux-open-url`
  on Termux.
- Files are read as UTF-8 (with or without BOM, falling back to Latin-1) and
  written with `\n` line endings via a temporary file and an atomic rename.
- No key binding relies on Ctrl+I, Ctrl+M or Ctrl+H, which terminals send as
  Tab, Enter and Backspace.
