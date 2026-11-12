"""The Inkmill application.

``InkmillApp`` owns the registries (commands, menus, formats, exporters), the
list of open documents and one :class:`InkEditor` per document. Widgets and
commands talk to it through the small set of public methods below; commands
live in :mod:`inkmill.builtin` and plugins add more through
:class:`inkmill.plugins.PluginAPI`.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import ContentSwitcher, TextArea

from . import APP_NAME
from .commands import CommandRegistry, format_key
from .config import Settings, State, state_dir
from .documents import Document, DocumentList
from .export import builtin_exporters
from .formats import DocumentFormat, builtin_formats
from .menus import MenuModel
from .plugins import EventBus
from .recovery import RecoveryStore
from .screens.dialogs import ConfirmDialog, FindRequest
from .system import PreviewServer
from .themes import BUILTIN_THEMES, VARIABLE_DEFAULTS, derive_variables
from .widgets.editor import InkEditor
from .widgets.menubar import MenuScreen, MenuStrip
from .widgets.panel import NARROW, SidePanel
from .widgets.statusbar import StatusBar

log = logging.getLogger("inkmill")

MENU_KEYS = ("escape", "f10", "alt+equals_sign")


@dataclass
class Handoff:
    """What one app instance passes to the next when Inkmill restarts in place."""

    docs: list[dict[str, Any]] = field(default_factory=list)
    active: int = 0
    # Recovery snapshot keys written just before the restart, discarded once
    # the documents are back on screen.
    snapshot_keys: list[str] = field(default_factory=list)
    message: str = ""


class InkmillApp(App):
    TITLE = APP_NAME
    ENABLE_COMMAND_PALETTE = True
    COMMAND_PALETTE_BINDING = "ctrl+p"

    CSS = """
    Screen { color: $foreground; layers: base overlay; }
    #menubar { dock: top; display: none; }
    #menubar.-pinned { display: block; }
    #main { height: 1fr; }
    #page { width: 1fr; height: 100%; align-horizontal: center; }
    #main.-panel-full > #page { display: none; }
    #editors { width: 100%; height: 100%; }
    Toast { background: $im-dialog-bg; color: $im-dialog-fg; }
    """

    BINDINGS = [Binding("ctrl+q", "quit", show=False, priority=True)]

    def __init__(
        self,
        paths: Iterable[Path] = (),
        *,
        settings: Settings | None = None,
        state: State | None = None,
        load_plugins: bool = True,
        plugin_dir: Path | None = None,
        handoff: Handoff | None = None,
    ) -> None:
        super().__init__()
        self.handoff = handoff
        # Set by request_restart(); __main__ starts a fresh app when it is.
        self.restart_handoff: Handoff | None = None
        # Set by the update commands: "restart" starts the newly installed
        # Inkmill after this one exits; pending_update runs an update once it
        # has exited (Windows, where running files are locked).
        self.after_exit: str | None = None
        self.pending_update: Any = None
        self.update_installed: str | None = None
        self.events = EventBus(self)
        self.status_segments: list[Callable[["InkmillApp"], str | None]] = []
        self.services: dict[str, Any] = {}
        self.decoration_styles: dict[str, Any] = {}
        from .export.markdown import clear_extensions

        clear_extensions()  # plugins register theirs again below
        self.plugin_dir = plugin_dir
        self.settings = settings or Settings.load()
        self.state = state or State()
        self.commands = CommandRegistry()
        self.menus = MenuModel()
        self.formats = builtin_formats()
        self.exporters = builtin_exporters()
        self.docs = DocumentList()
        self.recovery = RecoveryStore(state_dir() / "recovery")
        self.find_request = FindRequest("next", "")
        self.initial_paths = [Path(p) for p in paths]
        self.preview_dir = Path(tempfile.mkdtemp(prefix="inkmill-preview-"))
        self.preview_server = PreviewServer(self.preview_dir)
        self._status_timer: Timer | None = None
        self._recovery_timer: Timer | None = None

        from .builtin import register_builtins

        register_builtins(self)
        for theme in BUILTIN_THEMES:
            self.register_theme(theme)
        self.plugin_info = []
        if load_plugins:
            from .plugins import load_plugins as _load

            self.plugin_info = _load(self, plugin_dir)
        unknown = self.commands.apply_key_overrides(self.settings.keys)
        self._startup_warnings = [f"Unknown command in [keys]: {u}" for u in unknown]
        for info in self.plugin_info:
            if info.error:
                from .pluginmanager import previous_version

                hint = "; View > Plugins can roll it back" if previous_version(info.name, plugin_dir) else ""
                self._startup_warnings.append(f"Plugin {info.name} failed to load{hint}")
            elif info.skipped and info.skipped != "disabled":
                self._startup_warnings.append(f"Plugin {info.name} not loaded: {info.skipped}")
        self._bind_command_keys()
        self.theme = self.settings.theme if self.settings.theme in self.available_themes else "wordperfect"

    # -- theme and keys --------------------------------------------------

    def get_theme_variable_defaults(self) -> dict[str, str]:
        # Worked out per theme, so any Textual theme gets matching menus and
        # dialogs; a theme's own im-* variables still win.
        try:
            derived = derive_variables(self.current_theme)
        except Exception:
            derived = VARIABLE_DEFAULTS
        return {**super().get_theme_variable_defaults(), **VARIABLE_DEFAULTS, **derived}

    def watch_theme(self, _theme: str) -> None:
        if not self.screen_stack:
            return
        for editor in self.query(InkEditor):
            editor.apply_syntax_theme(self.current_theme)

    def _bind_command_keys(self) -> None:
        for command in self.commands:
            if command.keys:
                self._bindings.bind(",".join(command.keys), f"command('{command.id}')", show=False, priority=True)
        for key in MENU_KEYS:
            self._bindings.bind(key, "open_menu", show=False, priority=True)
        for i, menu in enumerate(self.menus):
            if menu.accelerator:
                self._bindings.bind(f"alt+{menu.accelerator}", f"open_menu({i})", show=False, priority=True)

    def on_main_screen(self) -> bool:
        return len(self.screen_stack) <= 1 and not isinstance(self.screen, MenuScreen)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "open_menu":
            # Esc inside the side panel closes the panel instead.
            if self.screen_stack and self.panel_has_focus() and parameters == ():
                return False
            return self.on_main_screen()
        if action == "command":
            command = self.commands.get(str(parameters[0])) if parameters else None
            if command is None:
                return False
            if not command.global_ and not self.on_main_screen():
                return False
            return command.is_enabled(self)
        return True

    def menu_hint(self) -> str:
        return f"{format_key(MENU_KEYS[0])}/{format_key(MENU_KEYS[1])}: menu  {APP_NAME}"

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield MenuStrip(list(self.menus), id="menubar", hint=self.menu_hint())
        with Horizontal(id="main"):
            with Container(id="page"):
                yield ContentSwitcher(id="editors")
            yield SidePanel(id="panel")
        yield StatusBar(id="status")

    async def on_mount(self) -> None:
        self.apply_view_settings()
        if self.handoff is not None:
            await self._restore_handoff(self.handoff)
        else:
            opened = False
            paths = self.initial_paths
            if not paths and self.settings.restore_session:
                paths = [Path(p) for p in self.state.session if Path(p).exists()]
            for path in paths:
                if await self.open_path(path, quiet=bool(not self.initial_paths)):
                    opened = True
            if not opened:
                await self.new_document()
        if self.settings.recovery_interval > 0:
            self._recovery_timer = self.set_interval(self.settings.recovery_interval, self.snapshot_unsaved)
        # Nothing has been snapshotted yet this session, so any snapshot on
        # disk was left behind by a session that did not exit cleanly.
        leftovers = self.recovery.list()
        if leftovers:
            self.notify(
                f"{len(leftovers)} unsaved document(s) were recovered. Use File > Recover to restore.",
                title="Recovery",
                timeout=10,
            )
        for warning in self._startup_warnings:
            self.notify(warning, severity="warning", timeout=8)
        if self.handoff is not None and self.handoff.message:
            self.status.flash(self.handoff.message, seconds=6)
        else:
            self.status.flash(f"{format_key(MENU_KEYS[0])} opens the menu  |  F1 help  |  F5 list files", seconds=6)
        self.events.emit("ready")

    def apply_view_settings(self) -> None:
        menubar = self.query_one("#menubar", MenuStrip)
        menubar.set_class(self.settings.menu_bar == "always", "-pinned")
        self.query_one(StatusBar).display = self.settings.status_bar
        switcher = self.query_one("#editors", ContentSwitcher)
        width = self.settings.page_width
        switcher.styles.max_width = width + 2 if width > 0 else None
        for editor in self.query(InkEditor):
            editor.soft_wrap = self.settings.soft_wrap
            editor.rich = self.settings.rich_view
            editor.apply_syntax_theme(self.current_theme)

    # -- side panel --------------------------------------------------------

    @property
    def panel(self) -> SidePanel:
        base = self.screen_stack[0] if self.screen_stack else self.screen
        return base.query_one(SidePanel)

    def panel_has_focus(self) -> bool:
        try:
            return self.panel.visible and self.panel.contains_focus()
        except Exception:
            return False

    async def show_panel(self, widget, *, title: str, owner: str, hint: str = "", focus: bool = True) -> None:
        await self.panel.show(widget, title, owner, hint, focus=focus)
        self.call_after_refresh(self._repaint_editors)

    def hide_panel(self) -> None:
        panel = self.panel
        if panel.visible:
            owner = panel.owner
            panel.hide()
            editor = self.active_editor
            if editor is not None:
                editor.focus()
            self.call_after_refresh(self._repaint_editors)
            self.events.emit("panel_closed", owner)

    def _repaint_editors(self) -> None:
        # The editors change width when the panel opens or closes. TextArea
        # re-wraps on resize but can keep painting the old lines, so wrap and
        # repaint explicitly once the new layout is in place.
        for editor in self.query(InkEditor):
            editor._rewrap_and_refresh_virtual_size()
            editor.refresh()

    def toggle_panel_focus(self) -> None:
        panel = self.panel
        if not panel.visible:
            self.status.flash("The side panel is closed.")
            return
        if panel.contains_focus():
            editor = self.active_editor
            if editor is not None:
                editor.focus()
        else:
            panel.focus_content()

    def on_resize(self, event) -> None:
        try:
            self.panel.set_narrow(event.size.width < NARROW)
        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "escape" and self.panel_has_focus():
            event.stop()
            self.hide_panel()

    def refresh_editor_styles(self) -> None:
        """Re-apply highlight styles after a plugin registers a new one."""
        if not self.screen_stack:
            return
        for editor in self.query(InkEditor):
            editor.apply_syntax_theme(self.current_theme)

    @property
    def status(self) -> StatusBar:
        # The status bar lives on the base screen, whatever is on top of it.
        base = self.screen_stack[0] if self.screen_stack else self.screen
        return base.query_one(StatusBar)

    # -- documents ---------------------------------------------------------

    @property
    def active_document(self) -> Document | None:
        return self.docs.active

    @property
    def active_editor(self) -> InkEditor | None:
        doc = self.docs.active
        if doc is None:
            return None
        try:
            return self.query_one(f"#doc-{doc.id}", InkEditor)
        except Exception:
            return None

    def editor_for(self, doc: Document) -> InkEditor | None:
        try:
            return self.query_one(f"#doc-{doc.id}", InkEditor)
        except Exception:
            return None

    def default_format(self) -> DocumentFormat:
        return self.formats.get(self.settings.default_format) or self.formats.get("markdown")  # type: ignore[return-value]

    def default_extension(self) -> str:
        doc = self.active_document
        fmt = doc.format if doc else self.default_format()
        return fmt.default_extension

    async def _add(self, doc: Document) -> Document:
        dropped = self.docs.replace_if_pristine(doc)
        self.docs.add(doc)
        editor = InkEditor(doc, soft_wrap=self.settings.soft_wrap, highlight=self.settings.syntax_highlight)
        editor.apply_syntax_theme(self.current_theme)
        editor.rich = self.settings.rich_view
        switcher = self.query_one("#editors", ContentSwitcher)
        await switcher.mount(editor)
        if dropped is not None:
            old = self.editor_for(dropped)
            if old is not None:
                await old.remove()
        self.activate(doc)
        return doc

    async def new_document(self, text: str = "", fmt: DocumentFormat | None = None) -> Document:
        doc = Document(format=fmt or self.default_format(), text=text, saved_text="")
        return await self._add(doc)

    async def open_path(self, path: Path, *, quiet: bool = False) -> Document | None:
        path = path.expanduser()
        existing = self.docs.find_path(path)
        if existing is not None:
            self.activate(existing)
            return existing
        if path.is_dir():
            if not quiet:
                self.notify(f"{path} is a folder.", severity="warning")
            return None
        fmt = self.formats.for_path(path, self.settings.default_format)
        try:
            doc = Document.from_file(path, fmt)
        except OSError as exc:
            if not quiet:
                self.notify(f"Cannot open {path.name}: {exc.strerror or exc}", severity="error")
            return None
        self.state.add_recent(path)
        await self._add(doc)
        self.events.emit("document_opened", doc)
        return doc

    def activate(self, doc: Document) -> None:
        self.docs.activate(doc)
        switcher = self.query_one("#editors", ContentSwitcher)
        switcher.current = f"doc-{doc.id}"
        editor = self.editor_for(doc)
        if editor is not None:
            editor.focus()
        self.check_disk_changes(doc)
        self.update_status(full=True)
        self.events.emit("document_activated", doc)

    def check_disk_changes(self, doc: Document) -> None:
        """Reload a document another program changed, or warn if it has edits."""
        if not doc.changed_on_disk():
            return
        if doc.dirty:
            doc.disk_mtime = doc.current_mtime()
            self.notify(
                f"{doc.title} changed on disk and has unsaved edits here. Saving will overwrite the other version.",
                severity="warning",
                timeout=10,
            )
            return
        if self.reload_document(doc):
            self.status.flash(f"Reloaded {doc.title}: it changed on disk.")

    def reload_document(self, doc: Document) -> bool:
        """Read ``doc`` from disk again, keeping the cursor where it was.

        Refuses (returns False) when the document has unsaved edits.
        """
        if doc.path is None or doc.dirty or not doc.path.exists():
            return False
        try:
            text = doc.format.load(doc.path)
        except OSError:
            return False
        doc.disk_mtime = doc.current_mtime()
        if text == doc.text:
            return True
        editor = self.editor_for(doc)
        doc.saved_text = text
        doc.text = text
        if editor is not None:
            row, col = editor.cursor_location
            editor.load_text(text)
            last = max(0, editor.document.line_count - 1)
            row = min(row, last)
            editor.cursor_location = (row, min(col, len(editor.document.get_line(row))))
        self.recovery.clear(doc)
        if doc is self.docs.active:
            self.update_status(full=True)
        self.events.emit("document_reloaded", doc)
        return True

    def replace_document_text(self, doc: Document, text: str) -> None:
        """Replace a document's whole text as one undoable edit."""
        editor = self.editor_for(doc)
        if editor is None:
            doc.text = text
            return
        end = editor.document.end
        editor.replace(text, (0, 0), end)
        doc.text = editor.text

    async def close_document(self, doc: Document) -> None:
        editor = self.editor_for(doc)
        self.recovery.clear(doc)
        self.docs.remove(doc)
        if editor is not None:
            await editor.remove()
        self.events.emit("document_closed", doc)
        if not self.docs.docs:
            await self.new_document()
        else:
            self.activate(self.docs.active)  # type: ignore[arg-type]

    def save_document(self, doc: Document, path: Path | None = None) -> bool:
        try:
            target = doc.save(path)
        except (OSError, ValueError) as exc:
            reason = getattr(exc, "strerror", None) or str(exc)
            self.notify(f"Save failed: {reason}", severity="error")
            return False
        self.recovery.clear(doc)
        self.state.add_recent(target)
        self.state.save()
        self.status.flash(f"Saved {target}")
        self.update_status(full=True)
        self.after_save(doc)
        self.events.emit("document_saved", doc)
        return True

    def after_save(self, doc: Document) -> None:
        """Reload settings when the settings file itself was edited and saved."""
        if doc.path is not None and doc.path.resolve() == Settings.path().resolve():
            self.settings = Settings.load()
            if self.settings.theme in self.available_themes:
                self.theme = self.settings.theme
            self.apply_view_settings()
            self.status.flash("Settings reloaded. Key changes apply after restart.")

    def file_moved(self, old: Path, new: Path) -> None:
        doc = self.docs.find_path(old)
        if doc is not None:
            doc.path = new
            doc.disk_mtime = doc.current_mtime()
            self.update_status(full=True)
        self.events.emit("file_moved", old, new)

    def file_deleted(self, path: Path) -> None:
        doc = self.docs.find_path(path)
        if doc is not None:
            doc.saved_text = "\0deleted"
            doc.disk_mtime = None
            self.update_status(full=True)
        self.events.emit("file_deleted", path)

    async def confirm_discard(self, doc: Document) -> bool:
        """Ask to save a dirty document. Returns False if the user cancels."""
        if not doc.dirty:
            return True
        self.activate(doc)
        answer = await self.push_screen_wait(
            ConfirmDialog(
                "Unsaved changes",
                f"Save changes to {doc.title}?",
                (("yes", "&Yes"), ("no", "&No"), ("cancel", "&Cancel")),
            )
        )
        if answer == "yes":
            from .builtin import save_as

            if doc.path is None:
                return await save_as(self, doc)
            return self.save_document(doc)
        return answer == "no"

    # -- status ------------------------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        editor = event.text_area
        if isinstance(editor, InkEditor):
            if editor.tidy_table_while_typing():
                return  # the tidy posts its own Changed
            editor.doc.text = editor.text
            self.update_status()

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        if event.text_area is self.active_editor:
            self.update_status(position_only=True)

    def update_status(self, *, full: bool = False, position_only: bool = False) -> None:
        doc = self.docs.active
        editor = self.active_editor
        if doc is None or editor is None:
            return
        try:
            status = self.status
        except Exception:
            return
        row, col = editor.cursor_location
        per_page = max(1, self.settings.lines_per_page)
        number = self.docs.number_of(doc)
        total = len(self.docs)
        doc_label = f"Doc {number}" if total == 1 else f"Doc {number}/{total}"
        self._position = f"{doc_label}  Pg {row // per_page + 1} Ln {row % per_page + 1} Pos {col + 1}"
        if not position_only:
            marker = " *" if doc.dirty else ""
            title = doc.display_title if self.settings.show_titles else ""
            status.set_left(f"{doc.display_path}{marker}", title=title)
            self.sub_title = title or doc.title
        if full or not hasattr(self, "_segments"):
            self._segments = self._segment_text()
        if full or not hasattr(self, "_words"):
            self._words = doc.word_count()
        elif not position_only:
            if self._status_timer is not None:
                self._status_timer.stop()
            self._status_timer = self.set_timer(0.4, self._recount)
        status.set_right(f"{self._segments}{self._words:,} words  {self._position}")

    def _segment_text(self) -> str:
        parts = []
        for func in self.status_segments:
            try:
                text = func(self)
            except Exception:
                log.exception("status segment failed")
                continue
            if text:
                parts.append(text)
        return "".join(f"{p}  " for p in parts)

    def _recount(self) -> None:
        self._status_timer = None
        doc = self.docs.active
        if doc is None:
            return
        try:
            status = self.status
        except Exception:  # the app is shutting down
            return
        self._words = doc.word_count()
        status.set_right(f"{self._segments}{self._words:,} words  {self._position}")
        self.events.emit("document_changed", doc)

    # -- menus and commands ----------------------------------------------

    def action_open_menu(self, index: int = 0) -> None:
        def chosen(command_id: str | None) -> None:
            editor = self.active_editor
            if editor is not None:
                editor.focus()
            if command_id:
                self.run_command(command_id)

        self.push_screen(MenuScreen(index), chosen)

    def action_command(self, command_id: str) -> None:
        self.run_command(command_id)

    def run_command(self, command_id: str) -> None:
        command = self.commands.get(command_id)
        if command is None:
            self.notify(f"Unknown command: {command_id}", severity="error")
            return
        if not command.is_enabled(self):
            self.bell()
            return

        async def runner() -> None:
            try:
                await command.run(self)
            except Exception as exc:  # A failing command must never lose the session.
                log.exception("command %s failed", command_id)
                self.notify(f"{command.label} failed: {exc}", severity="error", timeout=8)

        self.run_worker(runner(), group="command", exit_on_error=False)

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        for command in sorted(self.commands, key=lambda c: c.label.lower()):
            if not command.palette or not command.is_enabled(self):
                continue
            label = command.label.replace("&", "").rstrip(".")
            help_text = command.description or (f"Key: {format_key(command.keys[0])}" if command.keys else "")
            yield SystemCommand(label, help_text, lambda cid=command.id: self.run_command(cid))

    # -- recovery and shutdown -------------------------------------------

    def snapshot_unsaved(self) -> None:
        for doc in self.docs:
            if doc.dirty and doc.text:
                self.recovery.snapshot(doc)

    async def action_quit(self) -> None:
        self.run_command("file.quit")

    def build_handoff(self, message: str = "") -> Handoff:
        handoff = Handoff(message=message)
        for doc in self.docs:
            editor = self.editor_for(doc)
            if doc.dirty and doc.text:
                self.recovery.snapshot(doc)
                handoff.snapshot_keys.append(doc.recovery_key)
            handoff.docs.append(
                {
                    "path": str(doc.path) if doc.path else None,
                    "text": doc.text,
                    "saved_text": doc.saved_text,
                    "format": doc.format.id,
                    "untitled_number": doc.untitled_number,
                    "disk_mtime": doc.disk_mtime,
                    "cursor": tuple(editor.cursor_location) if editor is not None else (0, 0),
                }
            )
        active = self.docs.active
        handoff.active = self.docs.docs.index(active) if active in self.docs.docs else 0
        return handoff

    async def _restore_handoff(self, handoff: Handoff) -> None:
        restored: list[Document] = []
        for item in handoff.docs:
            fmt = self.formats.get(item.get("format", "")) or self.default_format()
            path = Path(item["path"]) if item.get("path") else None
            doc = Document(
                format=fmt,
                path=path,
                text=item.get("text", ""),
                saved_text=item.get("saved_text", ""),
                untitled_number=item.get("untitled_number", 0),
            )
            doc.disk_mtime = item.get("disk_mtime")
            await self._add(doc)
            editor = self.editor_for(doc)
            if editor is not None:
                try:
                    editor.cursor_location = tuple(item.get("cursor", (0, 0)))
                except Exception:
                    pass
            restored.append(doc)
            if path is not None:
                self.events.emit("document_opened", doc)
        if not restored:
            await self.new_document()
        else:
            self.activate(restored[min(handoff.active, len(restored) - 1)])
        for key in handoff.snapshot_keys:
            self.recovery.discard(key)

    def request_restart(self, message: str = "Restarted.") -> None:
        """Close this app and start a new one with the same documents open.

        Plugins are loaded again from scratch, which is how installs and
        updates take effect. Unsaved text survives; undo history does not.
        """
        self.restart_handoff = self.build_handoff(message)
        self.state.session = [str(d.path.resolve()) for d in self.docs if d.path is not None]
        self.state.save()
        self.preview_server.close()
        self.exit()

    async def shutdown(self) -> None:
        """Called by the quit command after every dirty document is settled."""
        self.state.session = [str(d.path.resolve()) for d in self.docs if d.path is not None]
        self.state.save()
        for doc in self.docs:
            if not doc.dirty:
                self.recovery.clear(doc)
        self.preview_server.close()
        self.exit()
