# Writing Inkmill plugins

A plugin is a Python module with a `register(api)` function. Inkmill calls it
once at startup with a `PluginAPI` object, and everything the plugin adds goes
through that object.

## Where plugins live

Inkmill loads plugins from two places:

1. `*.py` files in the plugins folder. `inkmill --paths` prints its location,
   which is `~/.config/inkmill/plugins` on Linux and Termux and
   `%LOCALAPPDATA%\inkmill\plugins` on Windows. Files starting with `_` are
   skipped.
2. Installed packages declaring an entry point in the `inkmill.plugins` group:

   ```toml
   [project.entry-points."inkmill.plugins"]
   wordstats = "inkmill_wordstats:register"
   ```

A plugin that raises during `register` is reported in Help > About and as a
startup notice; Inkmill keeps running without it. To turn one off, list it in
settings.toml:

```toml
[plugins]
disabled = ["word_goal"]
```

## Commands

```python
def register(api):
    @api.command("stamp.time", "Insert &Time", "ctrl+f9", menu="format")
    def insert_time(app):
        from datetime import datetime
        app.active_editor.insert(datetime.now().strftime("%H:%M"))
```

`api.command(id, label, keys="", *, menu=None, description="", enabled=None)`
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
