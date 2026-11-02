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
from pathlib import Path
from typing import Iterable

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Container
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
from .recovery import RecoveryStore
from .screens.dialogs import ConfirmDialog, FindRequest
from .system import PreviewServer
from .themes import BUILTIN_THEMES, VARIABLE_DEFAULTS
from .widgets.editor import InkEditor
from .widgets.menubar import MenuScreen, MenuStrip
from .widgets.statusbar import StatusBar

log = logging.getLogger("inkmill")

MENU_KEYS = ("escape", "f10", "alt+equals_sign")


class InkmillApp(App):
    TITLE = APP_NAME
    ENABLE_COMMAND_PALETTE = True
    COMMAND_PALETTE_BINDING = "ctrl+p"

    CSS = """
    Screen { background: $background; color: $foreground; layers: base overlay; }
    #menubar { dock: top; display: none; }
    #menubar.-pinned { display: block; }
    #page { width: 100%; height: 1fr; align-horizontal: center; }
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
    ) -> None:
        super().__init__()
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
        self._startup_warnings += [f"Plugin {p.name} failed to load" for p in self.plugin_info if p.error]
        self._bind_command_keys()
        self.theme = self.settings.theme if self.settings.theme in self.available_themes else "wordperfect"

    # -- theme and keys --------------------------------------------------

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return {**super().get_theme_variable_defaults(), **VARIABLE_DEFAULTS}

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
        with Container(id="page"):
            yield ContentSwitcher(id="editors")
        yield StatusBar(id="status")

    async def on_mount(self) -> None:
        self.apply_view_settings()
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
        self.status.flash(f"{format_key(MENU_KEYS[0])} opens the menu  |  F1 help  |  F5 list files", seconds=6)

    def apply_view_settings(self) -> None:
        menubar = self.query_one("#menubar", MenuStrip)
        menubar.set_class(self.settings.menu_bar == "always", "-pinned")
        self.query_one(StatusBar).display = self.settings.status_bar
        switcher = self.query_one("#editors", ContentSwitcher)
        width = self.settings.page_width
        switcher.styles.max_width = width + 2 if width > 0 else None
        for editor in self.query(InkEditor):
            editor.soft_wrap = self.settings.soft_wrap

    @property
    def status(self) -> StatusBar:
        return self.query_one(StatusBar)

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
        return await self._add(doc)

    def activate(self, doc: Document) -> None:
        self.docs.activate(doc)
        switcher = self.query_one("#editors", ContentSwitcher)
        switcher.current = f"doc-{doc.id}"
        editor = self.editor_for(doc)
        if editor is not None:
            editor.focus()
        self.update_status(full=True)

    async def close_document(self, doc: Document) -> None:
        editor = self.editor_for(doc)
        self.recovery.clear(doc)
        self.docs.remove(doc)
        if editor is not None:
            await editor.remove()
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
            self.update_status(full=True)

    def file_deleted(self, path: Path) -> None:
        doc = self.docs.find_path(path)
        if doc is not None:
            doc.saved_text = "\0deleted"
            self.update_status(full=True)

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
            status.set_left(f"{doc.display_path}{marker}")
            self.sub_title = doc.title
        if full or not hasattr(self, "_words"):
            self._words = doc.word_count()
        elif not position_only:
            if self._status_timer is not None:
                self._status_timer.stop()
            self._status_timer = self.set_timer(0.4, self._recount)
        status.set_right(f"{self._words:,} words  {self._position}")

    def _recount(self) -> None:
        self._status_timer = None
        doc = self.docs.active
        if doc is not None:
            self._words = doc.word_count()
            self.status.set_right(f"{self._words:,} words  {self._position}")

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

    async def shutdown(self) -> None:
        """Called by the quit command after every dirty document is settled."""
        self.state.session = [str(d.path.resolve()) for d in self.docs if d.path is not None]
        self.state.save()
        for doc in self.docs:
            if not doc.dirty:
                self.recovery.clear(doc)
        self.preview_server.close()
        self.exit()
