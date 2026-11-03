# Writing Inkmill plugins

A plugin is a Python package with a `register(api)` function and a
`plugin.toml` manifest. Inkmill calls `register` once at startup with a
`PluginAPI` object, and everything the plugin adds goes through that object.

The plugins that ship with Inkmill live in the repository's `plugins/`
folder and are working examples. `examples/plugins/word_goal` is the
smallest complete plugin. `outline` shows the side panel, `spelling` editor
highlights, `comments` and `links` Markdown export extensions and services,
`binder` a service other plugins use, and `git_sync` and `pandoc` outside
programs.

## Layout and manifest

```
plugins/my_plugin/
  plugin.toml
  __init__.py      # def register(api): ...
  README.md        # shown in View > Plugins
  helpers.py       # any other modules; import them with "from . import helpers"
```

```toml
id = "my_plugin"                 # must match the folder name
name = "My Plugin"
version = "1.2.0"
requires_inkmill = ">=0.2"       # any PEP 440 specifier, e.g. ">=0.2,<1"
summary = "One line for the plugin list."
author = "Your Name"
license = "MIT"

[[requires]]                     # an outside program the plugin uses
command = "pandoc"
purpose = "every export and import"
url = "https://pandoc.org/installing.html"
install = { windows = "winget install JohnMacFarlane.Pandoc", macos = "brew install pandoc", linux = "sudo apt install pandoc", termux = "pkg install pandoc" }

[[requires]]
any_of = ["typst", "weasyprint", "xelatex"]   # any one of these will do
optional = true                               # the plugin works without it, with less
purpose = "PDF export"
```

`[[requires]]` entries are checked when the plugin is installed: View >
Plugins lists each program as found or not found with the install command
for the user's platform, and installing a plugin whose required program is
missing asks first. `inkmill --plugins` reports missing programs too. A
plugin still loads without them, so its commands should check
(`shutil.which`) and explain what to install. The older `external =
["git"]` list is read as required programs without install hints.

`requires_inkmill` is checked twice: View > Plugins will not install a
plugin the running Inkmill cannot run, and the loader skips one copied in by
hand and says why. Plugins may import only the standard library and
Inkmill; there is no way to install extra packages alongside them.

## Where plugins are loaded from

1. Folders in the plugins folder (`inkmill --paths` prints it:
   `~/.config/inkmill/plugins` on Linux and Termux,
   `%LOCALAPPDATA%\inkmill\plugins` on Windows). This is where View >
   Plugins installs.
2. Single `*.py` files in the same folder, for quick personal plugins. They
   have no version and the manager lists them as unmanaged. Names starting
   with `_` are skipped.
3. Installed Python packages declaring an entry point in the
   `inkmill.plugins` group:

   ```toml
   [project.entry-points."inkmill.plugins"]
   wordstats = "inkmill_wordstats:register"
   ```

`inkmill --plugins` lists what Inkmill finds and whether each one loads. A
plugin that raises during `register` is reported as a startup notice and in
Help > About; Inkmill keeps running without it. To turn one off, use 5 in
View > Plugins, or list it in settings.toml:

```toml
[plugins]
disabled = ["word_goal"]
```

## Publishing to the plugin index

View > Plugins reads `plugins/index.json`, which lists every plugin with its
manifest fields and a SHA-256 hash of each file. To add or update a plugin
in this repository:

1. Put it in `plugins/<id>/` and bump `version` in its `plugin.toml` for any
   change (CI refuses changed files under an unchanged version).
2. Run `python scripts/build_plugin_index.py`.
3. Commit the plugin and the regenerated `index.json` together. CI runs the
   script with `--check` and fails if the index is stale.

Users get the new version the next time they press 6 (Check Again) or open
View > Plugins. The manager can also read an index from another URL or from
a local clone, so a fork or a private collection works the same way.

## Commands

```python
def register(api):
    @api.command("stamp.time", "Insert &Time", "ctrl+f9", menu="format")
    def insert_time(app):
        from datetime import datetime
        app.active_editor.insert(datetime.now().strftime("%H:%M"))
```

`api.command(id, label, keys="", *, menu=None, description="", enabled=None, separator=False)`
registers a command and returns a decorator.

- `id` should be namespaced with the plugin's name to avoid collisions.
- `label` is the menu text. An `&` marks the accelerator letter.
- `keys` is a comma-separated list of Textual key names (`ctrl+s`, `f5`,
  `alt+x`, `shift+f3`). Users can override it in `[keys]`.
- `menu` adds the command to that menu. An existing id (`file`, `edit`,
  `format`, `document`, `view`, `help`) appends to it; a new id creates a menu
  before Help.
- `enabled(app) -> bool` greys the item out and disables its key when false.

Handlers receive the app. They may be plain functions or `async` functions.
Async handlers can show dialogs and wait for the answer:

```python
from inkmill.screens.dialogs import InputDialog, ConfirmDialog, ChoiceDialog

async def handler(app):
    name = await app.push_screen_wait(InputDialog("Title", "Prompt:", "default"))
```

An exception inside a handler is shown as an error notice and does not end the
session.

## Events


```python
@api.on("document_saved")
def saved(app, doc):
    app.status.flash(f"{doc.title}: {doc.word_count()} words")
```

| Event | Arguments | When |
|-------|-----------|------|
| `ready` | | Startup finished and the first documents are open |
| `document_opened` | `doc` | A file was opened (not new untitled documents) |
| `document_activated` | `doc` | The user switched to a document |
| `document_saved` | `doc` | After a successful save |
| `document_closed` | `doc` | After a document was closed |
| `document_reloaded` | `doc` | Inkmill re-read a file another program changed |
| `document_changed` | `doc` | The active document was edited; sent once typing pauses (about half a second) |
| `panel_closed` | `owner` | The side panel closed; `owner` is the plugin that filled it |
| `file_moved` | `old`, `new` | List Files moved or renamed a file |
| `file_deleted` | `path` | List Files deleted a file |

A handler may be `async`; it then runs in a worker and can show dialogs. An
exception in a handler is reported and does not stop other handlers.

## Status line

```python
@api.status_segment
def segment(app):
    return "draft 3"        # or None to show nothing
```

The text appears before the word count. Segments are recomputed when the
status line is fully refreshed (switching documents, saving) and when you
call `api.refresh_status()`. Keep the function cheap: do slow work (a
subprocess, reading many files) elsewhere, cache it, then call
`refresh_status()`. `git_sync` shows the pattern.

## The side panel

```python
from textual.widgets import OptionList

@api.command("notes.show", "&Notes", "f7", menu="document")
async def show(app):
    if api.owns_panel:
        api.hide_panel()
        return
    widget = OptionList(*["first", "second"])
    await api.show_panel(widget, "Notes", hint="Enter go  Ctrl+T text  Esc close")
```

`api.show_panel(widget, title, hint)` puts any Textual widget in the panel
on the right, replacing what was there, and focuses it. `api.owns_panel`
says whether yours is showing, `api.hide_panel()` closes it, and
`app.panel.set_title(text)` updates the title. Ctrl+T moves the focus
between the text and the panel and Esc closes it; handle other keys in your
widget. Clean up on the `panel_closed` event.

## Highlighting text

```python
from rich.style import Style

api.decoration_style("notes.mark", lambda v: Style(underline=True, color=v["im-mark"]))

@api.on("document_changed")
def mark(app, doc):
    editor = app.active_editor
    ranges = [((0, 0), (0, 5), "notes.mark")]      # (start, end, style) as (row, column)
    editor.set_decorations("notes", ranges)
```

`api.decoration_style(name, style)` registers a style; pass a function of
the theme's variables (`im-heading`, `im-mark`, `im-dim`, ...) so it follows
the screen theme. `editor.set_decorations(owner, ranges)` replaces your
ranges; `editor.clear_decorations(owner)` removes them. Ranges do not move
with later edits, so recompute them on `document_changed`. Use
`editor.location_of(index)` to turn a character offset into (row, column).

`inkmill.markup.mask_non_prose(text)` returns the text with front matter,
code, links, URLs and HTML blanked out but every position unchanged, which
is what you want before searching prose with a regular expression.

## Markdown export

```python
def extend(md):                        # md is a markdown_it.MarkdownIt
    md.inline.ruler.before("link", "mention", my_rule)

api.markdown_extension(extend)
```

The function runs whenever Inkmill builds its Markdown parser for HTML
export and preview. `links` adds a wikilink inline rule; `comments`
rewrites the source in a core rule.

## Services

One plugin can offer an object to the others:

```python
api.provide("binder", BinderService())     # in Binder

binder = api.service("binder")             # anywhere else; None if Binder is not installed
if binder is not None:
    chapters = binder.chapters(binder.binder_for(doc.path))
```

Always handle `None`, since the user may not have the other plugin. The
bundled services are `binder` (`binder_for`, `title`, `chapters`, `read`,
`manuscript_markdown`, `research`, `project`, `set_field`), `comments`
(`final`, `original`, `marks`) and `links` (`plain`, `find`).

## Opening things

`inkmill.system.open_url(url)` opens a web address in the browser and
`inkmill.system.open_file(path)` opens a file in its usual app, on every
platform Inkmill runs on, Termux included.

## Blocking work

`await api.run_in_thread(func, *args)` runs a blocking call off the UI
thread from an async handler, so the screen stays responsive while git or a
converter runs.

## Front matter

`inkmill.frontmatter` reads and edits YAML front matter without a YAML
dependency and without disturbing what it does not touch:

```python
from inkmill import frontmatter

meta = frontmatter.read(doc.text)               # {"title": "...", "tags": ["a", "b"]}
text = frontmatter.update(doc.text, {"status": "draft", "old_key": None})
app.replace_document_text(doc, text)            # one undoable edit
```

`update` sets or removes only the keys it is given; comments, ordering and
nested values it does not understand stay exactly as they were.

## Changing documents

| Call | What it does |
|------|--------------|
| `app.replace_document_text(doc, text)` | Replace an open document's text as one undoable edit |
| `app.reload_document(doc)` | Re-read it from disk (refuses when it has unsaved edits) |
| `app.save_document(doc)` | Save, with the usual status message and `document_saved` event |
| `app.open_path(path)` | Open a file, or switch to it if it is open |
| `app.request_restart(message)` | Restart Inkmill in place, keeping documents open |

## Menus

```python
api.add_menu("tools", "&Tools")                      # before Help
api.add_menu_item("format", "stamp.time", after="format.date")
api.add_menu_item("tools", "stamp.time", separator=True)
```

## Working with the document

| Attribute | What it is |
|-----------|------------|
| `app.active_document` | The current `Document`: `.text`, `.path`, `.format`, `.dirty`, `.word_count()` |
| `app.active_editor` | Its `InkEditor`, a Textual `TextArea` with Markdown helpers |
| `app.docs` | Every open document, in order |
| `app.settings` | The `Settings` object; call `.save()` after changing it |
| `api.settings` | This plugin's own `[plugins.<name>]` table |
| `app.status.flash(text)` | Show a message in the status line |
| `app.notify(text)` | Show a toast |
| `app.run_command(id)` | Run any command by id |

Useful editor methods: `insert(text)`, `replace(text, start, end)`,
`selected_text`, `cursor_location`, `toggle_wrap(left, right)`,
`set_heading(level)`, `toggle_block(kind)`, `insert_block(lines)`,
`find(needle)`.

## Formats

A format converts between a file and the Markdown or plain text the editor
holds. To open a new file type, register a `DocumentFormat` with your own
`load(path) -> str` and `save(path, text)`:

```python
from inkmill.formats import DocumentFormat

def load_org(path):
    return convert_org_to_markdown(path.read_text())

api.register_format(DocumentFormat(
    id="org", name="Org mode", extensions=(".org",),
    load=load_org, save=save_org, markdown=True,
))
```

Set `markdown=True` when the text the editor shows is Markdown, so HTML export
and preview treat it as such.

## Exporters

```python
from inkmill.export import Exporter

def to_plain(doc, settings):
    return doc.text

api.register_exporter(Exporter("plain", "Plain text", ".txt", to_plain))
```

The function returns `str` or `bytes`. Once more than one exporter exists,
File > Export As lets the user pick. `inkmill.export.markdown.render(text)`
gives you the parsed HTML body, title and front matter if you want to build
on the HTML pipeline.

## Themes

Screen themes are Textual themes. Inkmill's own themes also set `im-*`
variables for the menu bar, dialogs, selection and status line; see
`inkmill/themes.py` for the full list. Any variable you leave out falls back to
a default, so a plain Textual `Theme` works too.

```python
from textual.theme import Theme

api.register_theme(Theme(
    name="sepia", primary="#8b5a2b", background="#f4ecd8", foreground="#3b2f2f",
    dark=False, variables={"im-menu-bg": "#e0d2b4", "im-heading": "#8b5a2b"},
))
```
