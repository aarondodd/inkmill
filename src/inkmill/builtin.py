"""Built-in commands and the default menu layout.

Each command is a small function taking the app. Plugins use the same
registry, so everything here doubles as an example of the plugin surface.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from . import APP_NAME, __version__
from .commands import format_key
from .config import Settings, config_dir
from .documents import Document
from .export.html import available_styles
from .menus import Menu, MenuItem, Separator
from .screens.dialogs import ChoiceDialog, ConfirmDialog, FindDialog, FindRequest, InputDialog, TextDialog
from .screens.files import FileManagerScreen
from .system import open_in_browser, platform_name

if TYPE_CHECKING:
    from .app import InkmillApp


def _has_doc(app: "InkmillApp") -> bool:
    return app.active_editor is not None


def _start_dir(app: "InkmillApp") -> Path:
    doc = app.active_document
    if doc is not None and doc.path is not None:
        return doc.path.parent
    for recent in app.state.recent:
        parent = Path(recent).parent
        if parent.is_dir():
            return parent
    return Path.cwd()


# -- File ----------------------------------------------------------------


async def new_file(app: "InkmillApp") -> None:
    await app.new_document()


async def list_files(app: "InkmillApp") -> None:
    result = await app.push_screen_wait(FileManagerScreen("open", _start_dir(app)))
    for path in result or []:
        await app.open_path(path)


async def open_recent(app: "InkmillApp") -> None:
    recent = [p for p in app.state.recent if Path(p).exists()]
    if not recent:
        app.notify("No recent files yet.")
        return
    choice = await app.push_screen_wait(ChoiceDialog("Recent Files", [(p, p) for p in recent]))
    if choice:
        await app.open_path(Path(choice))


async def save_as(app: "InkmillApp", doc: Document | None = None) -> bool:
    doc = doc or app.active_document
    if doc is None:
        return False
    name = doc.path.name if doc.path else f"{doc.title.lower().replace(' ', '-')}{doc.format.default_extension}"
    start = doc.path.parent if doc.path else _start_dir(app)
    target = await app.push_screen_wait(FileManagerScreen("save", start, name))
    if target is None:
        return False
    fmt = app.formats.for_path(target, doc.format.id)
    if target.suffix.lower() in fmt.extensions:
        doc.format = fmt
    return app.save_document(doc, target)


async def save(app: "InkmillApp") -> None:
    doc = app.active_document
    if doc is None:
        return
    if doc.path is None:
        await save_as(app, doc)
    else:
        app.save_document(doc)


async def save_all(app: "InkmillApp") -> None:
    count = 0
    for doc in list(app.docs):
        if not doc.dirty:
            continue
        if doc.path is None:
            app.activate(doc)
            if not await save_as(app, doc):
                return
        elif not app.save_document(doc):
            return
        count += 1
    app.status.flash(f"Saved {count} document(s)." if count else "Nothing to save.")


async def close_file(app: "InkmillApp") -> None:
    doc = app.active_document
    if doc is not None and await app.confirm_discard(doc):
        await app.close_document(doc)


async def revert(app: "InkmillApp") -> None:
    doc = app.active_document
    editor = app.active_editor
    if doc is None or editor is None or doc.path is None:
        return
    if doc.dirty:
        answer = await app.push_screen_wait(ConfirmDialog("Revert", f"Discard changes and reload {doc.title}?"))
        if answer != "yes":
            return
    text = doc.format.load(doc.path)
    doc.saved_text = text
    editor.load_text(text)
    doc.text = text
    app.recovery.clear(doc)
    app.update_status(full=True)


async def export_html(app: "InkmillApp") -> None:
    doc = app.active_document
    if doc is None:
        return
    exporter = app.exporters.get("html")
    stem = doc.path.stem if doc.path else doc.title.lower().replace(" ", "-")
    start = doc.path.parent if doc.path else _start_dir(app)
    default = str(start / f"{stem}{exporter.extension}")
    answer = await app.push_screen_wait(InputDialog("Export HTML", f"Style: {app.settings.export_style}.  Save to:", default))
    if not answer:
        return
    target = Path(answer).expanduser()
    if target.exists():
        if await app.push_screen_wait(ConfirmDialog("Replace?", f"{target.name} exists. Replace it?")) != "yes":
            return
    try:
        exporter.write(doc, app.settings, target)
    except OSError as exc:
        app.notify(f"Export failed: {exc.strerror or exc}", severity="error")
        return
    app.status.flash(f"Exported {target}")


async def export_as(app: "InkmillApp") -> None:
    """Pick any registered exporter (plugins can add more)."""
    exporters = list(app.exporters)
    if len(exporters) == 1:
        await export_html(app)
        return
    choice = await app.push_screen_wait(ChoiceDialog("Export As", [(e.id, f"{e.name} ({e.extension})") for e in exporters]))
    if choice == "html":
        await export_html(app)
    elif choice:
        doc = app.active_document
        exporter = app.exporters.get(choice)
        if doc is None or exporter is None:
            return
        stem = doc.path.with_suffix(exporter.extension) if doc.path else _start_dir(app) / f"export{exporter.extension}"
        answer = await app.push_screen_wait(InputDialog(f"Export {exporter.name}", "Save to:", str(stem)))
        if answer:
            exporter.write(doc, app.settings, Path(answer).expanduser())
            app.status.flash(f"Exported {answer}")


async def preview(app: "InkmillApp") -> None:
    doc = app.active_document
    if doc is None:
        return
    exporter = app.exporters.get("html")
    target = app.preview_dir / f"preview-{doc.id}.html"
    exporter.write(doc, app.settings, target)
    try:
        how = open_in_browser(target, app.preview_server)
    except RuntimeError as exc:
        app.notify(f"Preview written to {target}, but {exc}.", severity="warning", timeout=10)
        return
    app.status.flash(f"Preview opened ({how}).")


async def export_style(app: "InkmillApp") -> None:
    styles = available_styles()
    choice = await app.push_screen_wait(
        ChoiceDialog(
            "HTML Style",
            [(name, name) for name in styles],
            app.settings.export_style,
            prompt=f"Add your own .css files to {config_dir() / 'styles'}",
        )
    )
    if choice:
        app.settings.export_style = choice
        app.settings.save()
        app.status.flash(f"HTML style: {choice}")


async def recover(app: "InkmillApp") -> None:
    snapshots = app.recovery.list()
    if not snapshots:
        app.notify("Nothing to recover.")
        return
    items = [
        (s.key, f"{s.title}  ({datetime.fromtimestamp(s.saved_at):%Y-%m-%d %H:%M})") for s in snapshots
    ]
    choice = await app.push_screen_wait(ChoiceDialog("Recover Unsaved Work", items))
    snap = next((s for s in snapshots if s.key == choice), None)
    if snap is None:
        return
    fmt = app.formats.get(snap.format) or app.default_format()
    text = snap.read()
    if snap.path:
        path = Path(snap.path)
        existing = app.docs.find_path(path)
        if existing is not None:
            await app.close_document(existing)
        saved = fmt.load(path) if path.exists() else ""
        doc = Document(format=fmt, path=path, text=text, saved_text=saved)
        await app._add(doc)
    else:
        await app.new_document(text, fmt)
    app.recovery.discard(snap.key)
    app.status.flash("Recovered. Save to keep it.")


async def quit_app(app: "InkmillApp") -> bool:
    """Quit after settling unsaved documents; False if the person cancelled."""
    for doc in list(app.docs):
        if not await app.confirm_discard(doc):
            return False
    for doc in app.docs:
        app.recovery.clear(doc)
    await app.shutdown()
    return True


# -- Edit ----------------------------------------------------------------


def _editor_action(name: str):
    def handler(app: "InkmillApp") -> None:
        editor = app.active_editor
        if editor is not None:
            getattr(editor, f"action_{name}")()

    return handler


def select_all(app: "InkmillApp") -> None:
    editor = app.active_editor
    if editor is not None:
        editor.select_all()


async def find(app: "InkmillApp", replace: bool = False) -> None:
    editor = app.active_editor
    if editor is None:
        return
    req = app.find_request
    needle = editor.selected_text if editor.selected_text and "\n" not in editor.selected_text else req.needle
    result: FindRequest | None = await app.push_screen_wait(
        FindDialog(needle, req.replacement, replace=replace, case=req.case, regex=req.regex)
    )
    editor.focus()
    if result is None or not result.needle:
        return
    app.find_request = result
    _do_find(app, result)


def _do_find(app: "InkmillApp", req: FindRequest) -> None:
    editor = app.active_editor
    if editor is None or not req.needle:
        return
    try:
        if req.action == "replace_all":
            n = editor.replace_all(req.needle, req.replacement, case=req.case, regex=req.regex)
            app.status.flash(f"Replaced {n} occurrence(s).")
            return
        if req.action == "replace":
            editor.replace_selection_if_match(req.needle, req.replacement, case=req.case)
        found = editor.find(req.needle, forward=req.action != "previous", case=req.case, regex=req.regex)
    except Exception as exc:  # Bad regular expression.
        app.notify(f"Search error: {exc}", severity="error")
        return
    if not found:
        app.status.flash(f"Not found: {req.needle}")


def find_next(app: "InkmillApp", forward: bool = True) -> None:
    req = app.find_request
    if not req.needle:
        app.run_command("edit.find")
        return
    _do_find(app, FindRequest("next" if forward else "previous", req.needle, req.replacement, req.case, req.regex))


async def goto_line(app: "InkmillApp") -> None:
    editor = app.active_editor
    if editor is None:
        return
    answer = await app.push_screen_wait(InputDialog("Go To", f"Line (1-{editor.document.line_count}) or Pg:Ln:", ""))
    if not answer:
        return
    per_page = max(1, app.settings.lines_per_page)
    try:
        if ":" in answer:
            pg, ln = (int(x) for x in answer.split(":", 1))
            line = (pg - 1) * per_page + ln
        else:
            line = int(answer)
    except ValueError:
        app.notify("Enter a line number, or page:line.", severity="warning")
        return
    row = max(0, min(line - 1, editor.document.line_count - 1))
    editor.move_cursor((row, 0))
    editor.scroll_cursor_visible(center=True)


def go_back(app: "InkmillApp") -> None:
    editor = app.active_editor
    if editor is not None and not editor.go_back():
        app.status.flash("Nowhere to go back to.")


# -- Format ----------------------------------------------------------------


def _wrap(left: str, right: str | None = None):
    def handler(app: "InkmillApp") -> None:
        editor = app.active_editor
        if editor is not None:
            editor.toggle_wrap(left, right)

    return handler


def _heading(level: int):
    def handler(app: "InkmillApp") -> None:
        editor = app.active_editor
        if editor is not None:
            editor.set_heading(level)

    return handler


def _block(kind: str):
    def handler(app: "InkmillApp") -> None:
        editor = app.active_editor
        if editor is not None:
            editor.toggle_block(kind)

    return handler


def toggle_task(app: "InkmillApp") -> None:
    editor = app.active_editor
    if editor is not None:
        editor.toggle_task_done()


async def insert_link(app: "InkmillApp") -> None:
    editor = app.active_editor
    if editor is None:
        return
    url = await app.push_screen_wait(InputDialog("Insert Link", "URL:", "https://"))
    editor.focus()
    if url and url != "https://":
        editor.insert_link("", url)


def insert_footnote(app: "InkmillApp") -> None:
    editor = app.active_editor
    if editor is not None:
        n = editor.insert_footnote()
        back = app.commands.get("edit.go_back")
        key = format_key(back.keys[0]) if back and back.keys else "Edit > Go Back"
        app.status.flash(f"Footnote {n}: type the note, then {key} returns to the text.")


async def insert_table(app: "InkmillApp") -> None:
    from .markup import make_table

    editor = app.active_editor
    if editor is None:
        return
    answer = await app.push_screen_wait(InputDialog("Insert Table", "Columns x rows:", "3x2"))
    editor.focus()
    if not answer:
        return
    try:
        cols, rows = (int(x) for x in answer.lower().replace(" ", "").split("x", 1))
    except ValueError:
        app.notify("Use the form 3x2.", severity="warning")
        return
    editor.insert_block(make_table(min(cols, 20), min(rows, 200)))


def tidy_table(app: "InkmillApp") -> None:
    editor = app.active_editor
    if editor is not None and not editor.tidy_table():
        app.status.flash("The cursor is not in a table.")


def insert_rule(app: "InkmillApp") -> None:
    editor = app.active_editor
    if editor is not None:
        editor.insert_block(["---"])


def insert_code_block(app: "InkmillApp") -> None:
    editor = app.active_editor
    if editor is None:
        return
    selected = editor.selected_text
    if selected:
        start, end = sorted(editor.selection)
        editor.replace(f"```\n{selected.rstrip()}\n```", start, end)
    else:
        editor.insert_block(["```", "", "```"])
        row = editor.cursor_location[0]
        editor.move_cursor((row + 1, 0))


def insert_date(app: "InkmillApp") -> None:
    editor = app.active_editor
    if editor is not None:
        editor.insert(datetime.now().strftime("%Y-%m-%d"))


# -- Document ----------------------------------------------------------------


def next_doc(app: "InkmillApp", step: int = 1) -> None:
    doc = app.docs.cycle(step)
    if doc is not None:
        app.activate(doc)


async def doc_list(app: "InkmillApp") -> None:
    items = []
    for i, doc in enumerate(app.docs, 1):
        marker = " *" if doc.dirty else ""
        items.append((str(doc.id), f"Doc {i}  {doc.display_path}{marker}"))
    active = app.active_document
    choice = await app.push_screen_wait(ChoiceDialog("Documents", items, str(active.id) if active else None))
    if choice:
        doc = next((d for d in app.docs if str(d.id) == choice), None)
        if doc is not None:
            app.activate(doc)


async def doc_info(app: "InkmillApp") -> None:
    doc = app.active_document
    if doc is None:
        return
    text = doc.text
    words = doc.word_count()
    paragraphs = sum(1 for block in text.split("\n\n") if block.strip())
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    rows = [
        ("File", doc.display_path),
        ("Format", doc.format.name),
        ("Words", f"{words:,}"),
        ("Characters", f"{len(text):,}"),
        ("Paragraphs", f"{paragraphs:,}"),
        ("Lines", f"{text.count(chr(10)) + 1 if text else 0:,}"),
        ("Pages", f"{(text.count(chr(10)) // max(1, app.settings.lines_per_page)) + 1}"),
        ("Reading time", f"about {max(1, round(words / 230))} min"),
        ("Unsaved changes", "yes" if doc.dirty else "no"),
    ]
    for key, value in rows:
        table.add_row(key, value)
    await app.push_screen_wait(TextDialog("Document Information", table))


async def set_format(app: "InkmillApp") -> None:
    doc = app.active_document
    editor = app.active_editor
    if doc is None or editor is None:
        return
    choice = await app.push_screen_wait(ChoiceDialog("Document Format", [(f.id, f.name) for f in app.formats], doc.format.id))
    fmt = app.formats.get(choice) if choice else None
    if fmt is not None:
        doc.format = fmt
        if app.settings.syntax_highlight and fmt.language and fmt.language in editor.available_languages:
            editor.language = fmt.language
        else:
            editor.language = None
        app.update_status(full=True)


# -- View ----------------------------------------------------------------


async def choose_theme(app: "InkmillApp") -> None:
    names = sorted(app.available_themes)
    builtin = ["wordperfect", "grinder", "paper", "amber", "phosphor"]
    ordered = [n for n in builtin if n in names] + [n for n in names if n not in builtin]
    choice = await app.push_screen_wait(ChoiceDialog("Screen Theme", [(n, n) for n in ordered], app.theme))
    if choice:
        app.theme = choice
        app.settings.theme = choice
        app.settings.save()


def toggle_setting(name: str, message: str):
    def handler(app: "InkmillApp") -> None:
        value = not getattr(app.settings, name)
        setattr(app.settings, name, value)
        app.settings.save()
        app.apply_view_settings()
        app.status.flash(f"{message}: {'on' if value else 'off'}")

    return handler


def reading_view(app: "InkmillApp") -> None:
    from .screens.reading import ReadingScreen

    doc = app.active_document
    editor = app.active_editor
    if doc is None or editor is None:
        return
    if not doc.format.markdown:
        app.status.flash("The reading view is for Markdown documents.")
        return
    command = app.commands.get("view.reading")
    keys = command.keys if command else ()

    def done(_result) -> None:
        editor.focus()

    app.push_screen(
        ReadingScreen(
            editor.text,
            title=doc.title,
            row=editor.cursor_location[0],
            width=app.settings.page_width,
            close_keys=keys,
            emphasis_colors=app.settings.emphasis_colors,
        ),
        done,
    )


def toggle_menu_bar(app: "InkmillApp") -> None:
    app.settings.menu_bar = "auto" if app.settings.menu_bar == "always" else "always"
    app.settings.save()
    app.apply_view_settings()


async def page_width(app: "InkmillApp") -> None:
    answer = await app.push_screen_wait(
        InputDialog("Page Width", "Writing column width in characters (0 = full width):", str(app.settings.page_width))
    )
    if answer is None:
        return
    try:
        width = int(answer)
    except ValueError:
        app.notify("Enter a whole number.", severity="warning")
        return
    app.settings.page_width = max(0, width) if width == 0 else max(20, width)
    app.settings.save()
    app.apply_view_settings()


async def open_settings(app: "InkmillApp") -> None:
    path = Settings.path()
    if not path.exists():
        app.settings.save(path)
    await app.open_path(path)
    app.status.flash("Edit and save to apply. Key bindings apply after a restart.")


# -- Help ----------------------------------------------------------------


async def plugin_manager(app: "InkmillApp") -> None:
    from .screens.plugins import PluginManagerScreen

    result = await app.push_screen_wait(PluginManagerScreen())
    if result == "restart":
        app.request_restart("Restarted. Plugin changes are active.")


def restart(app: "InkmillApp") -> None:
    app.request_restart()


async def check_plugin_updates(app: "InkmillApp") -> None:
    """Startup check, when [plugin_manager] check_updates = "startup"."""
    import asyncio

    from .pluginmanager import PluginSourceError, Source, build_rows, fetch_index, installed_plugins

    if app.settings.plugin_manager.get("check_updates") != "startup":
        return
    try:
        index = await asyncio.to_thread(fetch_index, Source.from_settings(app.settings.plugin_manager))
    except PluginSourceError:
        return
    rows = build_rows(index, installed_plugins(app.plugin_dir))
    updates = [r.name for r in rows if r.has_update]
    if updates:
        app.notify(f"Plugin updates: {', '.join(updates)}. View > Plugins installs them.", title="Plugins", timeout=10)


# -- Inkmill updates ---------------------------------------------------------


def _update_record(app: "InkmillApp") -> dict:
    record = app.state.data.get("updates")
    if not isinstance(record, dict):
        record = {}
        app.state.data["updates"] = record
    return record


async def _fetch_release(app: "InkmillApp"):
    import asyncio
    import time

    from . import updates

    release = await asyncio.to_thread(updates.fetch_release, updates.source_url(app.settings.updates))
    record = _update_record(app)
    record["checked"] = time.time()
    record["latest"] = release.version
    app.state.save()
    return release


async def _plugin_updates(app: "InkmillApp") -> list[str]:
    import asyncio

    from .pluginmanager import PluginSourceError, Source, build_rows, fetch_index, installed_plugins

    try:
        index = await asyncio.to_thread(fetch_index, Source.from_settings(app.settings.plugin_manager))
    except PluginSourceError:
        return []
    return [r.name for r in build_rows(index, installed_plugins(app.plugin_dir)) if r.has_update]


async def check_for_updates(app: "InkmillApp") -> None:
    """Help > Check for Updates: say what is new and install it where possible."""
    import asyncio

    from . import updates

    app.status.flash("Checking for updates...", seconds=30)
    try:
        release = await _fetch_release(app)
    except updates.UpdateError as exc:
        app.status.clear_flash()
        await app.push_screen_wait(TextDialog("Check for Updates", Text(f"Could not check for updates.\n\n{exc}")))
        return
    method = await asyncio.to_thread(updates.detect)
    plugins = await _plugin_updates(app)
    app.status.clear_flash()
    body = updates.describe(release, method)
    if plugins:
        body += f"\n\nPlugin updates: {', '.join(plugins)}. View > Plugins installs them."
    if not release.newer_than():
        await app.push_screen_wait(TextDialog("Check for Updates", Text(body)))
        return
    if app.pending_update is not None:
        body += "\n\nThe update is already set to run when you quit Inkmill."
    if method.automatic:
        choices = [("install", "&Install now"), ("later", "&Later")]
    elif method.deferred:
        choices = [("quit", "&Update and quit"), ("later", "&Later"), ("copy", "&Copy command")]
    else:
        choices = [("copy", "&Copy command"), ("close", "C&lose")]
    choice = await app.push_screen_wait(TextDialog(f"Inkmill {release.version}", Text(body), choices))
    if choice == "copy":
        app.copy_to_clipboard("\n".join(method.manual))
        app.status.flash("Copied the update command.")
    elif choice == "install":
        await install_update(app, release, method)
    elif choice == "quit":
        app.pending_update = method
        if not await quit_app(app):
            app.notify("The update runs when you quit Inkmill.", title="Update", timeout=8)


async def install_update(app: "InkmillApp", release, method, *, ask_restart: bool = True) -> bool:
    """Run the update command, confirm the new version is installed, offer a restart."""
    import asyncio

    from . import updates

    app.status.flash(f"Installing Inkmill {release.version}...", seconds=900)
    try:
        await asyncio.to_thread(updates.install, method)
    except updates.UpdateError as exc:
        app.status.clear_flash()
        body = f"{exc}\n\nTo update by hand, run:\n\n" + "\n".join(f"  {line}" for line in method.manual)
        if ask_restart:
            choice = await app.push_screen_wait(
                TextDialog("Update Failed", Text(body), [("copy", "&Copy command"), ("close", "C&lose")])
            )
            if choice == "copy":
                app.copy_to_clipboard("\n".join(method.manual))
        else:
            app.notify(f"Inkmill {release.version} could not be installed. Help > Check for Updates shows why.", severity="warning", timeout=10)
        return False
    installed = await asyncio.to_thread(updates.installed_version)
    app.status.clear_flash()
    if not updates.is_newer(installed, __version__):
        message = (
            f"The update command finished, but Inkmill {installed or 'of an unknown version'} is still installed. "
            "To update by hand, run:\n\n" + "\n".join(f"  {line}" for line in method.manual)
        )
        if ask_restart:
            await app.push_screen_wait(TextDialog("Update Not Installed", Text(message)))
        else:
            app.notify(message, severity="warning", timeout=12)
        return False
    app.update_installed = installed
    if not ask_restart:
        app.notify(f"Inkmill {installed} is installed. It starts the next time you open Inkmill.", title="Update", timeout=10)
        return True
    choice = await app.push_screen_wait(
        ConfirmDialog(
            "Update Installed",
            f"Inkmill {installed} is installed.\nRestart now to use it? Unsaved documents are offered for saving first.",
            [("restart", "&Restart now"), ("later", "&Later")],
        )
    )
    if choice == "restart":
        app.after_exit = "restart"
        if not await quit_app(app):
            app.after_exit = None
    else:
        app.status.flash(f"Inkmill {installed} starts the next time you open Inkmill.", seconds=6)
    return True


async def startup_update_check(app: "InkmillApp") -> None:
    """Once a day by default ([updates] check), say when a new Inkmill is out."""
    import asyncio
    import time

    from . import updates

    table = app.settings.updates
    if not updates.due(_update_record(app), str(table.get("check", "daily")), time.time()):
        return
    try:
        release = await _fetch_release(app)
    except updates.UpdateError:
        return
    if not release.newer_than():
        return
    method = await asyncio.to_thread(updates.detect)
    if table.get("auto_install") is True and method.automatic:
        await install_update(app, release, method, ask_restart=False)
    elif table.get("auto_install") is True and method.deferred:
        app.pending_update = method
        app.notify(f"Inkmill {release.version} is installed when you quit.", title="Update", timeout=10)
    elif method.possible:
        app.notify(f"Inkmill {release.version} is available. Help > Check for Updates installs it.", title="Update", timeout=10)
    else:
        app.notify(f"Inkmill {release.version} is available. Help > Check for Updates shows how to update.", title="Update", timeout=10)


async def show_keys(app: "InkmillApp") -> None:
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Key")
    table.add_column("Command")
    table.add_row("Esc / F10 / Alt+=", "Open the menu bar")
    table.add_row("Alt+letter", "Open that menu directly")
    table.add_row("^P", "Command palette (search every command)")
    for menu in app.menus:
        for entry in menu.items:
            if not isinstance(entry, MenuItem):
                continue
            command = app.commands.get(entry.command)
            if command and command.keys:
                table.add_row(", ".join(format_key(k) for k in command.keys), command.label.replace("&", "").rstrip("."))
    await app.push_screen_wait(TextDialog("Keys", table))


MARKDOWN_HELP = """\
# Heading 1            ## Heading 2           ### Heading 3
**bold**   *italic*   ~~strikethrough~~   `code`
[link text](https://example.com)    ![image](picture.png)

- bullet item          1. numbered item       - [ ] task  - [x] done
> quoted text          > [!NOTE] callout (NOTE, TIP, IMPORTANT, WARNING, CAUTION)

| Column | Column |     Table. Put the cursor in it and use
|--------|-------:|     Format > Tidy Table to line up the pipes.
| cell   |   cell |

A sentence with a footnote.[^1]
[^1]: The footnote text.  (Format > Footnote numbers them for you.)

Term
: Definition

```python
code block with highlighting in the HTML output
```

---  on its own line is a horizontal rule.
A block of key: value lines between --- fences at the very top is front
matter; title, author, date, description and lang go into the HTML head.
"""


async def markdown_help(app: "InkmillApp") -> None:
    await app.push_screen_wait(TextDialog("Markdown Quick Reference", Text(MARKDOWN_HELP)))


async def about(app: "InkmillApp") -> None:
    from .updates import detect as detect_install

    lines = [
        f"{APP_NAME} {__version__}",
        "",
        "A distraction-free word processor for the terminal.",
        "Inspired by WordGrinder and WordPerfect 5.1 for DOS.",
        "",
        f"Platform: {platform_name()}",
        f"Settings: {Settings.path()}",
        f"Plugins:  {config_dir() / 'plugins'}",
        f"Installed with: {detect_install().label}",
    ]
    for info in app.plugin_info:
        status = "error" if info.error else (info.skipped or "loaded")
        version = f" {info.version}" if info.version else ""
        lines.append(f"  {info.name}{version}: {status}")
        if info.error:
            lines.append("    " + info.error.strip().splitlines()[-1])
    await app.push_screen_wait(TextDialog("About", Text("\n".join(lines))))


# -- registration ----------------------------------------------------------


def register_builtins(app: "InkmillApp") -> None:
    c = app.commands.add

    c("file.new", "&New", "ctrl+n")(new_file)
    c("file.open", "&Open / List Files...", "ctrl+o,f5", description="Browse, preview and manage files")(list_files)
    c("file.recent", "Open &Recent...")(open_recent)
    c("file.save", "&Save", "ctrl+s", enabled=_has_doc)(save)
    c("file.save_as", "Save &As...", "f12", enabled=_has_doc)(save_as)
    c("file.save_all", "Save A&ll")(save_all)
    c("file.revert", "Rever&t to Saved", enabled=lambda a: bool(a.active_document and a.active_document.path))(revert)
    c("file.close", "&Close", "ctrl+w", enabled=_has_doc)(close_file)
    c("file.export_html", "&Export HTML...", enabled=_has_doc)(export_html)
    c("file.export", "Export As...", enabled=_has_doc)(export_as)
    c("file.preview", "&Preview in Browser", "f9", enabled=_has_doc)(preview)
    c("file.html_style", "HTML St&yle...")(export_style)
    c("file.recover", "Reco&ver Unsaved Work...")(recover)
    c("file.quit", "E&xit", "ctrl+q", global_=True)(quit_app)

    c("edit.undo", "&Undo", "ctrl+z", enabled=_has_doc)(_editor_action("undo"))
    c("edit.redo", "&Redo", "ctrl+y", enabled=_has_doc)(_editor_action("redo"))
    c("edit.cut", "Cu&t", "ctrl+x", enabled=_has_doc)(_editor_action("cut"))
    c("edit.copy", "&Copy", "ctrl+c", enabled=_has_doc)(_editor_action("copy"))
    c("edit.paste", "&Paste", "ctrl+v", enabled=_has_doc)(_editor_action("paste"))
    c("edit.select_all", "Select &All", "ctrl+a", enabled=_has_doc)(select_all)
    c("edit.find", "&Find...", "ctrl+f", enabled=_has_doc)(find)
    c("edit.find_next", "Find &Next", "f3", enabled=_has_doc)(find_next)
    c("edit.find_previous", "Find Pre&vious", "shift+f3", enabled=_has_doc)(lambda a: find_next(a, False))
    c("edit.replace", "R&eplace...", "ctrl+r", enabled=_has_doc)(lambda a: find(a, replace=True))
    c("edit.goto", "&Go To Line...", "ctrl+g", enabled=_has_doc)(goto_line)
    c("edit.go_back", "Go &Back", "alt+b", enabled=_has_doc, description="Return from a footnote")(go_back)

    c("format.bold", "&Bold", "ctrl+b", enabled=_has_doc)(_wrap("**"))
    c("format.italic", "&Italic", "ctrl+e", enabled=_has_doc)(_wrap("*"))
    c("format.strike", "&Strikethrough", enabled=_has_doc)(_wrap("~~"))
    c("format.code", "Inline &Code", enabled=_has_doc)(_wrap("`"))
    c("format.heading1", "Heading &1", "alt+1", enabled=_has_doc)(_heading(1))
    c("format.heading2", "Heading &2", "alt+2", enabled=_has_doc)(_heading(2))
    c("format.heading3", "Heading &3", "alt+3", enabled=_has_doc)(_heading(3))
    c("format.paragraph", "&Normal Paragraph", "alt+0", enabled=_has_doc)(_heading(0))
    c("format.bullets", "B&ulleted List", enabled=_has_doc)(_block("bullet"))
    c("format.numbers", "Nu&mbered List", enabled=_has_doc)(_block("number"))
    c("format.tasks", "&Task List", enabled=_has_doc)(_block("task"))
    c("format.task_done", "Toggle Task &Done", "ctrl+d", enabled=_has_doc)(toggle_task)
    c("format.quote", "&Quote", enabled=_has_doc)(_block("quote"))
    c("format.link", "Insert &Link...", "ctrl+k", enabled=_has_doc)(insert_link)
    c("format.footnote", "&Footnote", "ctrl+f7", enabled=_has_doc)(insert_footnote)
    c("format.table", "Insert T&able...", enabled=_has_doc)(insert_table)
    c("format.tidy_table", "Tid&y Table", "ctrl+backslash", enabled=_has_doc)(tidy_table)
    c("format.rule", "&Horizontal Rule", enabled=_has_doc)(insert_rule)
    c("format.code_block", "Code Bloc&k", enabled=_has_doc)(insert_code_block)
    c("format.date", "Insert Dat&e", enabled=_has_doc)(insert_date)

    c("doc.next", "&Next Document", "f6,ctrl+pagedown")(next_doc)
    c("doc.previous", "&Previous Document", "shift+f6,ctrl+pageup")(lambda a: next_doc(a, -1))
    c("doc.list", "&Switch To...", "ctrl+l")(doc_list)
    c("doc.info", "&Information...", enabled=_has_doc)(doc_info)
    c("doc.format", "Document &Format...", enabled=_has_doc)(set_format)

    c("view.theme", "Screen &Theme...")(choose_theme)
    c("view.menu_bar", "Pin &Menu Bar")(toggle_menu_bar)
    c("view.status_bar", "&Status Bar")(toggle_setting("status_bar", "Status bar"))
    c("view.wrap", "Soft &Wrap")(toggle_setting("soft_wrap", "Soft wrap"))
    c("view.rich", "R&ich View", "alt+f3", description="Format Markdown as you write: bold shown bold, markup dimmed")(
        toggle_setting("rich_view", "Rich view")
    )
    c("view.emphasis_colors", "Emphasis C&olors", description="Color bold and italic text too, for terminals that cannot show them")(
        toggle_setting("emphasis_colors", "Emphasis colors")
    )
    c("view.reading", "Re&ading View", "shift+f7", enabled=_has_doc, description="Read the document fully formatted")(reading_view)
    c("view.page_width", "&Page Width...")(page_width)
    c("view.settings", "Settings &File...")(open_settings)
    c("view.palette", "&Command Palette...", "ctrl+p")(lambda a: a.action_command_palette())
    c("view.panel_focus", "Switch to Side Pan&el", "ctrl+t", description="Move between the text and the side panel")(lambda a: a.toggle_panel_focus())
    c("view.panel_close", "Close Si&de Panel", enabled=lambda a: a.panel.visible)(lambda a: a.hide_panel())
    c("view.plugins", "Pl&ugins...", description="Install, update and remove plugins")(plugin_manager)
    c("app.restart", "Restart Inkmill", description="Reload plugins; open documents stay open")(restart)

    c("help.keys", "&Keys", "f1")(show_keys)
    c("help.markdown", "&Markdown Reference")(markdown_help)
    c("help.updates", "Check for &Updates...", description="See whether a newer Inkmill is out, and install it")(check_for_updates)
    c("help.about", "&About")(about)

    S = Separator
    M = MenuItem
    app.menus.add_menu(Menu("file", "&File", [
        M("file.new"), M("file.open"), M("file.recent"), S(),
        M("file.save"), M("file.save_as"), M("file.save_all"), M("file.revert"), S(),
        M("file.preview"), M("file.export_html"), M("file.html_style"), S(),
        M("file.recover"), M("file.close"), M("file.quit"),
    ]))
    app.menus.add_menu(Menu("edit", "&Edit", [
        M("edit.undo"), M("edit.redo"), S(),
        M("edit.cut"), M("edit.copy"), M("edit.paste"), M("edit.select_all"), S(),
        M("edit.find"), M("edit.find_next"), M("edit.find_previous"), M("edit.replace"), S(),
        M("edit.goto"), M("edit.go_back"),
    ]))
    app.menus.add_menu(Menu("format", "F&ormat", [
        M("format.bold"), M("format.italic"), M("format.strike"), M("format.code"), S(),
        M("format.heading1"), M("format.heading2"), M("format.heading3"), M("format.paragraph"), S(),
        M("format.bullets"), M("format.numbers"), M("format.tasks"), M("format.task_done"), M("format.quote"), S(),
        M("format.link"), M("format.footnote"), M("format.table"), M("format.tidy_table"),
        M("format.rule"), M("format.code_block"), M("format.date"),
    ]))
    app.menus.add_menu(Menu("document", "&Document", [
        M("doc.next"), M("doc.previous"), M("doc.list"), S(), M("doc.info"), M("doc.format"),
    ]))
    app.menus.add_menu(Menu("view", "&View", [
        M("view.theme"), M("view.menu_bar"), M("view.status_bar"), M("view.wrap"), M("view.page_width"), S(),
        M("view.rich"), M("view.reading"), M("view.emphasis_colors"), S(),
        M("view.panel_focus"), M("view.panel_close"), S(),
        M("view.palette"), M("view.plugins"), M("view.settings"),
    ]))
    app.events.on("ready", check_plugin_updates)
    app.events.on("ready", startup_update_check)
    app.menus.add_menu(Menu("help", "&Help", [M("help.keys"), M("help.markdown"), S(), M("help.updates"), M("help.about")]))
