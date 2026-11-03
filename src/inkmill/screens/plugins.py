"""View > Plugins: browse, install, update and remove plugins.

The left pane lists every plugin from the configured index plus anything
already in the plugins folder; the right pane shows the highlighted plugin's
details and README. Plugins change only after a restart, which the screen
offers when you leave it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markdown import Markdown
from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Label, Static

from .. import __version__
from ..pluginmanager import (
    STATUS_TEXT,
    PluginSourceError,
    Row,
    Source,
    build_rows,
    check_requirements,
    describe_missing,
    fetch_index,
    install,
    installed_plugins,
    remove,
    rollback,
)
from ..plugins import describe_requirement, plugins_dir
from .dialogs import ChoiceDialog, ConfirmDialog, InputDialog
from .files import FileTable

if TYPE_CHECKING:
    from ..app import InkmillApp


class PluginManagerScreen(Screen):
    """Dismisses with ``"restart"`` when the user chose to restart, else None."""

    DEFAULT_CSS = """
    PluginManagerScreen { background: $background; color: $foreground; }
    #pm-header { height: 1; padding: 0 1; }
    #pm-source { width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    #pm-mode { width: auto; color: $im-dim; }
    #pm-body { height: 1fr; }
    #pm-list-pane { width: 11fr; border: solid $im-dim; }
    #pm-detail-pane { width: 9fr; border: solid $im-dim; padding: 0 1; }
    #pm-detail-pane.-hidden { display: none; }
    PluginManagerScreen.-look #pm-list-pane { display: none; }
    PluginManagerScreen.-look #pm-detail-pane { display: block; }
    #pm-detail-title { color: $im-heading; height: 1; margin-bottom: 1; }
    #pm-info { height: 1; padding: 0 1; color: $im-dim; }
    #pm-info.-pending { color: $im-heading; }
    #pm-options { height: auto; padding: 0 1; background: $im-status-bg; color: $im-status-fg; }
    """

    BINDINGS = [Binding("escape", "close", show=False)]

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Row] = []
        self.index_error: str | None = None
        self.pending_restart = False
        self.busy = False
        self._readmes: dict[str, str] = {}

    @property
    def inkmill(self) -> "InkmillApp":
        return self.app  # type: ignore[return-value]

    @property
    def source(self) -> Source:
        return Source.from_settings(self.inkmill.settings.plugin_manager)

    @property
    def directory(self):
        return getattr(self.inkmill, "plugin_dir", None) or plugins_dir()

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="pm-header"):
            yield Label("", id="pm-source")
            yield Label(f"Plugins  (Inkmill {__version__})", id="pm-mode")
        with Horizontal(id="pm-body"):
            with Vertical(id="pm-list-pane"):
                yield FileTable(cursor_type="row", zebra_stripes=False, id="pm-table")
            with Vertical(id="pm-detail-pane"):
                yield Label("", id="pm-detail-title")
                with VerticalScroll(id="pm-detail-scroll"):
                    yield Static("", id="pm-detail")
        yield Label("Reading the plugin index...", id="pm-info")
        yield Static(self._options_text(), id="pm-options")

    def _options_text(self) -> Text:
        items = [
            "1 Install",
            "2 Remove",
            "3 Update",
            "4 Update All",
            "5 Enable/Disable",
            "6 Check Again",
            "7 Source",
            "8 Roll Back",
            "L Look",
            "R Restart",
            "Esc Close",
        ]
        text = Text()
        for i, item in enumerate(items):
            key, _, label = item.partition(" ")
            if i:
                text.append("; ")
            text.append(key, style="bold")
            text.append(" " + label)
        return text

    def on_mount(self) -> None:
        table = self.query_one(FileTable)
        table.add_column("Plugin", key="name")
        table.add_column("Installed", key="installed")
        table.add_column("Available", key="available")
        table.add_column("Status", key="status")
        self.query_one("#pm-source", Label).update(self.source.label)
        table.focus()
        self.reload()

    def on_resize(self, event: events.Resize) -> None:
        pane = self.query_one("#pm-detail-pane")
        pane.set_class(event.size.width < 90 and not self.has_class("-look"), "-hidden")

    # -- data --------------------------------------------------------------

    def info(self, message: str, *, pending: bool = False) -> None:
        label = self.query_one("#pm-info", Label)
        label.update(message)
        label.set_class(pending, "-pending")

    @work(exclusive=True, group="pm-load")
    async def reload(self, message: str | None = None) -> None:
        import asyncio

        source = self.source
        self.query_one("#pm-source", Label).update(source.label)
        self.info("Reading the plugin index...")
        try:
            index = await asyncio.to_thread(fetch_index, source)
            self.index_error = None
        except PluginSourceError as exc:
            index = []
            self.index_error = str(exc)
        self._readmes.clear()
        self.refresh_rows(index)
        if message:
            self.info(message, pending=self.pending_restart)
        elif self.index_error:
            self.info(f"Index unavailable: {self.index_error}. Showing installed plugins only.")
        else:
            updates = sum(1 for r in self.rows if r.status == "update")
            self.info(
                f"{len(index)} plugin(s) in the index; {updates} update(s) available."
                + ("  Press R to restart and apply changes." if self.pending_restart else ""),
                pending=self.pending_restart,
            )

    def refresh_rows(self, index=None) -> None:
        if index is None:
            index = [r.entry for r in self.rows if r.entry is not None]
        disabled = set(self.inkmill.settings.plugins.get("disabled", []) or [])
        load_info = {p.name: p for p in getattr(self.inkmill, "plugin_info", [])}
        self.rows = build_rows(
            index, installed_plugins(self.directory), disabled=disabled, load_info=load_info, directory=self.directory
        )
        table = self.query_one(FileTable)
        current = self.current_row()
        table.clear()
        for row in self.rows:
            status = STATUS_TEXT[row.status]
            style = "bold" if row.status in ("update", "error") else ""
            table.add_row(
                Text(row.name, style=style),
                row.installed_version or "-",
                row.available_version or "-",
                Text(status, style=style),
                key=row.id,
            )
        if current is not None:
            for i, row in enumerate(self.rows):
                if row.id == current.id:
                    table.move_cursor(row=i)
                    break
        self.update_detail()

    def current_row(self) -> Row | None:
        table = self.query_one(FileTable)
        if not self.rows or table.cursor_row is None or not (0 <= table.cursor_row < len(self.rows)):
            return None
        return self.rows[table.cursor_row]

    def on_data_table_row_highlighted(self, _event) -> None:
        self.update_detail()

    def on_data_table_row_selected(self, _event) -> None:
        if not self.busy:
            self.do_default()

    def update_detail(self) -> None:
        row = self.current_row()
        title = self.query_one("#pm-detail-title", Label)
        detail = self.query_one("#pm-detail", Static)
        if row is None:
            title.update("")
            detail.update("No plugins found." if not self.index_error else "")
            return
        title.update(row.name)
        manifest = (row.entry.manifest if row.entry else None) or (row.installed.manifest if row.installed else None)
        lines = Text()

        def field(label: str, value: str) -> None:
            if value:
                lines.append(f"{label:<11}", style="bold")
                lines.append(value + "\n")

        field("Status", STATUS_TEXT[row.status])
        field("Installed", row.installed_version or ("yes" if row.installed else ""))
        field("Available", row.available_version)
        if manifest:
            field("Requires", describe_requirement(manifest.requires_inkmill) if manifest.requires_inkmill else "")
            field("Author", manifest.author)
            field("License", manifest.license)
            for req in manifest.requires:
                path = req.found()
                state = "found" if path else ("not found, optional" if req.optional else "NOT FOUND")
                field("Needs", f"{req.name} ({state})" + (f": {req.purpose}" if req.purpose else ""))
                if not path and req.install_hint():
                    field("", f"Install: {req.install_hint()}")
        if row.previous:
            field("Roll back", f"version {row.previous} is kept (8)")
        if row.installed:
            field("Folder", str(row.installed.path))
        if row.load_skipped:
            field("Not loaded", row.load_skipped)
        if row.load_error:
            lines.append("\nLoad error:\n", style="bold")
            lines.append(row.load_error.strip().splitlines()[-1] + "\n")
        summary = manifest.summary if manifest else ""
        if summary:
            lines.append("\n" + summary + "\n")
        readme = self._readmes.get(row.id)
        if readme is None:
            readme = self._local_readme(row)
            if readme is None and row.entry is not None and "README.md" in row.entry.files:
                self.fetch_readme(row)
                readme = ""
            self._readmes.setdefault(row.id, readme or "")
        if readme:
            from rich.console import Group

            detail.update(Group(lines, Text(""), Markdown(readme)))
        else:
            detail.update(lines)

    def _local_readme(self, row: Row) -> str | None:
        if row.installed is None or not row.installed.path.is_dir():
            return None
        if row.has_update:
            return None
        readme = row.installed.path / "README.md"
        try:
            return readme.read_text(encoding="utf-8")
        except OSError:
            return None

    @work(group="pm-readme")
    async def fetch_readme(self, row: Row) -> None:
        import asyncio

        if row.entry is None:
            return
        try:
            data = await asyncio.to_thread(self.source.read, f"{row.entry.path}/README.md")
            self._readmes[row.id] = data.decode("utf-8", errors="replace")
        except PluginSourceError:
            self._readmes[row.id] = ""
            return
        current = self.current_row()
        if current is not None and current.id == row.id:
            self.update_detail()

    # -- actions -----------------------------------------------------------

    def changed(self, message: str) -> None:
        self.pending_restart = True
        self.refresh_rows()
        self.info(f"{message}  Press R to restart and apply.", pending=True)

    def on_key(self, event: events.Key) -> None:
        if self.busy:
            return
        actions = {
            "1": self.do_install,
            "i": self.do_install,
            "2": self.do_remove,
            "delete": self.do_remove,
            "3": self.do_update,
            "u": self.do_update,
            "4": self.do_update_all,
            "a": self.do_update_all,
            "5": self.do_toggle,
            "d": self.do_toggle,
            "6": self.do_check,
            "c": self.do_check,
            "7": self.do_source,
            "s": self.do_source,
            "8": self.do_rollback,
            "b": self.do_rollback,
            "l": self.do_look,
            "r": self.do_restart,
        }
        key = event.character.lower() if event.character and event.character.isprintable() else event.key
        action = actions.get(key)
        if action is not None:
            event.stop()
            event.prevent_default()
            action()

    def do_look(self) -> None:
        self.toggle_class("-look")
        self.query_one("#pm-detail-pane").set_class(False, "-hidden")

    def do_default(self) -> None:
        row = self.current_row()
        if row is None:
            return
        if row.status == "available":
            self.do_install()
        elif row.status == "update":
            self.do_update()
        else:
            self.do_look()

    def do_check(self) -> None:
        self.reload()

    def do_restart(self) -> None:
        self.dismiss("restart")

    @work(exclusive=True, group="pm-action")
    async def do_install(self, update: bool = False) -> None:
        row = self.current_row()
        if row is None:
            return
        if row.entry is None:
            self.info(f"{row.name} is not in the index, so there is nothing to install.")
            return
        if not row.entry.compatible:
            self.info(f"{row.name} {row.available_version} needs {describe_requirement(row.entry.manifest.requires_inkmill)}.")
            return
        if row.installed and not update and not row.has_update:
            self.info(f"{row.name} {row.installed_version} is already installed.")
            return
        if row.installed and not row.installed.managed and not update:
            answer = await self.app.push_screen_wait(
                ConfirmDialog("Replace?", f"{row.name} was copied in by hand. Replace it with version {row.available_version}?")
            )
            if answer != "yes":
                return
        if not await self._requirements_ok(row):
            return
        if row.installed is None:
            answer = await self.app.push_screen_wait(
                ConfirmDialog(
                    "Install plugin",
                    f"Install {row.name} {row.available_version}?\nPlugins are Python code and run with your permissions.",
                )
            )
            if answer != "yes":
                return
        await self._install_rows([row])

    async def _requirements_ok(self, row: Row) -> bool:
        """Warn about missing programs before installing. False to stop."""
        manifest = row.entry.manifest if row.entry else None
        required, optional = check_requirements(manifest)
        if required:
            answer = await self.app.push_screen_wait(
                ConfirmDialog(
                    "Missing programs",
                    f"{row.name} needs programs that are not installed:\n\n{describe_missing(required)}\n\n"
                    "Install them, then press 6 to check again. You can also install the plugin now; "
                    "its commands will explain what is missing until you do.",
                    (("yes", "&Install anyway"), ("no", "&Cancel")),
                )
            )
            return answer == "yes"
        if optional:
            self.notify(
                f"{row.name} works without these, with fewer features:\n{describe_missing(optional)}",
                title="Optional programs not found",
                timeout=12,
            )
        return True

    def do_update(self) -> None:
        row = self.current_row()
        if row is None:
            return
        if not row.has_update:
            self.info(f"{row.name} has no update." if row.installed else f"{row.name} is not installed; 1 installs it.")
            return
        self.do_install(update=True)

    @work(exclusive=True, group="pm-action")
    async def do_update_all(self) -> None:
        rows = [r for r in self.rows if r.has_update]
        if not rows:
            self.info("Everything is up to date.")
            return
        await self._install_rows(rows)

    async def _install_rows(self, rows: list[Row]) -> None:
        import asyncio

        self.busy = True
        done, failed = [], []
        try:
            for row in rows:
                assert row.entry is not None
                self.info(f"Installing {row.name} {row.available_version}...")
                try:
                    await asyncio.to_thread(install, row.entry, self.source, self.directory)
                    done.append(f"{row.name} {row.available_version}")
                except (PluginSourceError, OSError) as exc:
                    failed.append(f"{row.name}: {exc}")
        finally:
            self.busy = False
        if failed:
            self.refresh_rows()
            self.info("Failed: " + "; ".join(failed), pending=self.pending_restart)
            if done:
                self.pending_restart = True
            return
        self.changed("Installed " + ", ".join(done) + ".")

    @work(exclusive=True, group="pm-action")
    async def do_remove(self) -> None:
        row = self.current_row()
        if row is None or row.installed is None:
            return
        answer = await self.app.push_screen_wait(
            ConfirmDialog("Remove plugin", f"Remove {row.name}? Its settings in settings.toml are kept.")
        )
        if answer != "yes":
            return
        try:
            remove(row.id, self.directory)
        except OSError as exc:
            self.info(f"Could not remove {row.name}: {exc}")
            return
        self.changed(f"Removed {row.name}.")

    def do_toggle(self) -> None:
        row = self.current_row()
        if row is None or row.installed is None:
            return
        settings = self.inkmill.settings
        disabled = list(settings.plugins.get("disabled", []) or [])
        if row.id in disabled:
            disabled.remove(row.id)
            message = f"Enabled {row.name}."
        else:
            disabled.append(row.id)
            message = f"Disabled {row.name}."
        settings.plugins["disabled"] = disabled
        settings.save()
        self.changed(message)

    @work(exclusive=True, group="pm-action")
    async def do_rollback(self) -> None:
        row = self.current_row()
        if row is None or not row.previous:
            self.info("No earlier version is kept for this plugin.")
            return
        answer = await self.app.push_screen_wait(
            ConfirmDialog("Roll back", f"Replace {row.name} {row.installed_version} with the kept version {row.previous}?")
        )
        if answer != "yes":
            return
        try:
            rollback(row.id, self.directory)
        except (PluginSourceError, OSError) as exc:
            self.info(str(exc))
            return
        self.changed(f"Rolled {row.name} back to {row.previous}.")

    @work(exclusive=True, group="pm-action")
    async def do_source(self) -> None:
        settings = self.inkmill.settings
        table = settings.plugin_manager
        current = self.source
        choice = await self.app.push_screen_wait(
            ChoiceDialog(
                "Plugin Source",
                [("online", "Online (the Inkmill repository)"), ("local", "Local folder (a clone of the repository)")],
                current.kind,
            )
        )
        if not choice:
            return
        if choice == "local":
            from pathlib import Path

            answer = await self.app.push_screen_wait(
                InputDialog("Local Plugin Source", "Folder holding plugins/index.json:", str(table.get("local_path", "")))
            )
            if not answer:
                return
            folder = Path(answer).expanduser()
            try:
                Source("local", str(folder)).index_file()
            except PluginSourceError as exc:
                self.info(str(exc))
                return
            table["local_path"] = str(folder)
        else:
            from ..pluginmanager import DEFAULT_INDEX_URL

            answer = await self.app.push_screen_wait(
                InputDialog("Online Plugin Source", "Index URL:", str(table.get("index_url") or DEFAULT_INDEX_URL))
            )
            if not answer:
                return
            if answer.strip() == DEFAULT_INDEX_URL:
                table.pop("index_url", None)
            else:
                table["index_url"] = answer.strip()
        table["source"] = choice
        settings.save()
        self.reload()

    def action_close(self) -> None:
        self._close()

    @work(exclusive=True, group="pm-action")
    async def _close(self) -> None:
        if self.pending_restart:
            answer = await self.app.push_screen_wait(
                ConfirmDialog(
                    "Restart Inkmill?",
                    "Plugin changes take effect after a restart. Your documents stay open.",
                    (("yes", "&Restart now"), ("no", "&Later")),
                )
            )
            if answer is None:
                return
            self.dismiss("restart" if answer == "yes" else None)
            return
        self.dismiss(None)
