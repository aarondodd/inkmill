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
  plugins.py        plugin discovery, manifests, version checks, events, PluginAPI
  pluginmanager.py  plugin index, install, update, rollback, remove
  frontmatter.py    read and edit YAML front matter without a YAML library
  recovery.py       crash recovery snapshots
  config.py         settings.toml and state.json
  system.py         platform detection and opening the browser
  themes.py         screen themes and editor syntax colors
  widgets/          InkEditor, MenuStrip and MenuScreen, StatusBar, SidePanel
  screens/          dialogs, List Files and the Plugins screen
plugins/            first-party plugins and the generated index.json
scripts/            build_plugin_index.py
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

## Events and the status line

`app.events` is a small bus. The app emits `ready`, `document_opened`,
`document_activated`, `document_saved`, `document_closed`,
`document_reloaded`, `file_moved` and `file_deleted`; plugins subscribe with
`api.on(name)`. Async handlers run in workers. Plugins also add status line
segments, functions recomputed on full status refreshes and shown before the
word count.

When a document becomes active, Inkmill compares the file's modification
time with the one it recorded at the last read or write. A clean document
that another program changed (a git pull, a sync tool) is reloaded with the
cursor kept; one with unsaved edits gets a warning instead.

## Side panel, highlights and services

The main screen is a horizontal row: the page (holding the editors) and a
`SidePanel` that stays hidden until a plugin calls `show_panel`. When it
opens or closes the editors change width, so the app re-wraps and repaints
them once the new layout is in place. Below 90 columns the panel takes the
whole row while it is open.

Plugin highlights ("decorations") are ranges an owner sets on an editor.
`InkEditor._build_highlight_map` adds them to TextArea's own syntax
highlights after converting character columns to the UTF-8 byte offsets
TextArea uses, and their styles join the editor's theme, so they draw with
or without tree-sitter.

The Markdown parser keeps a registry of extensions by plugin name; the app
clears it at startup so a restart does not register twice. Plugins expose
objects to each other through `app.services`.

## Plugins and restarting

A managed plugin is a folder with `plugin.toml` and `__init__.py`, loaded as
the package `inkmill_plugin_<id>` so it can hold several modules. The loader
skips a plugin whose `requires_inkmill` does not match and records why.

A manifest's `[[requires]]` entries name outside programs (one command, or
`any_of` several) with install hints per platform; the manager checks them
with `shutil.which` before installing and the loader never blocks on them.

The plugin manager reads an index (`plugins/index.json`, generated by
`scripts/build_plugin_index.py`) from a URL or a local folder, downloads each
file into a staging folder, checks its SHA-256 against the index, and only
then swaps the folder into place. The replaced version moves to
`plugins/.previous/<id>/` for rollback.

Python cannot unload a module cleanly, and plugins register commands, menus,
bindings and themes, so changes apply on restart. `__main__.run_app` runs the
app in a loop: `request_restart` builds a `Handoff` (each document's path,
text, saved text, format and cursor), exits, and the loop drops plugin
modules from `sys.modules` and starts a new app from the handoff. Unsaved
text survives; undo history does not. The same process is reused because
replacing it (`os.execv`) misbehaves under Windows terminals.

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
