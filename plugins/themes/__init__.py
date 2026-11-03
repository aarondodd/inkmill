"""Themes: more screen themes, a gallery with live preview, and theme files.

Bundled themes live in ``themes/*.toml`` inside this plugin. Your own go in
the ``themes`` folder next to settings.toml (View > Open Themes Folder), in
the same format, and load at startup. New Theme from Current writes a
complete file to start from and opens it; every save applies it at once.
"""

from __future__ import annotations

from pathlib import Path

from inkmill.config import config_dir
from inkmill.screens.dialogs import InputDialog, TextDialog
from inkmill.themes import BUILTIN_THEMES

from . import loader
from .gallery import GalleryScreen


def user_themes_dir() -> Path:
    return config_dir() / "themes"


def register(api):
    app = api.app
    infos: dict[str, loader.ThemeInfo] = {}
    errors: list[str] = []

    def add(info: loader.ThemeInfo) -> None:
        app.register_theme(info.theme)
        infos[info.theme.name] = info

    def load_all() -> list[str]:
        problems: list[str] = []
        bundled_dir = Path(__file__).parent / "themes"
        for source, folder in (("bundled", bundled_dir), ("yours", user_themes_dir())):
            found, bad = loader.load_folder(folder, source)
            problems += bad
            for info in found:
                add(info)
        return problems

    errors += load_all()

    def catalog() -> dict[str, loader.ThemeInfo]:
        """Every available theme, labeled with where it came from."""
        core = {t.name for t in BUILTIN_THEMES}
        out: dict[str, loader.ThemeInfo] = {}
        for name in app.available_themes:
            if name in infos:
                out[name] = infos[name]
                continue
            theme = app.get_theme(name)
            if theme is None or name == "textual-ansi":
                continue
            source = "inkmill" if name in core else "textual"
            out[name] = loader.ThemeInfo(theme, name.replace("-", " ").title(), "", source)
        return out

    def apply(name: str) -> None:
        app.theme = name
        app.settings.theme = name
        app.settings.save()

    def refresh_current() -> None:
        """Re-apply the current theme after its definition changed."""
        name = app.theme
        other = "textual-dark" if name != "textual-dark" else "textual-light"
        app.theme = other
        app.theme = name

    async def new_from(name: str) -> None:
        base = app.get_theme(name)
        if base is None:
            return
        default = f"my-{name}" if not name.startswith("my-") else f"{name}-2"
        new = await app.push_screen_wait(InputDialog("New Theme", "Name (lowercase letters, digits, dashes):", default))
        if not new:
            return
        new = new.strip().lower().replace(" ", "-")
        if not loader.NAME.match(new):
            app.notify("Use lowercase letters, digits and dashes.", severity="error")
            return
        folder = user_themes_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{new}.toml"
        if path.exists():
            app.notify(f"{path.name} already exists; opening it.", severity="warning")
        else:
            label = new.replace("-", " ").title()
            path.write_text(loader.to_toml(base, new, label, name), encoding="utf-8")
            try:
                add(loader.load_file(path, "yours"))
            except loader.ThemeFileError as exc:
                app.notify(str(exc), severity="error")
                return
            apply(new)
        await app.open_path(path)
        app.status.flash(f"Editing {path.name}. Save (Ctrl+S) to apply your changes.", seconds=8)

    # -- commands ----------------------------------------------------------------

    @api.command("themes.gallery", "Theme &Gallery...", menu="view", description="Pick a theme with a live preview")
    async def gallery(app):
        result = await app.push_screen_wait(GalleryScreen(catalog(), app.theme))
        if result is None:
            return
        action, name = result
        if action == "apply" and name:
            apply(name)
            app.status.flash(f"Theme: {catalog()[name].label}")
        elif action == "new" and name:
            await new_from(name)

    @api.command("themes.new", "&New Theme from Current...", menu="view",
                 description="Write an editable theme file based on the current theme")
    async def new_theme(app):
        await new_from(app.theme)

    @api.command("themes.reload", "&Reload Theme Files", menu="view")
    async def reload(app):
        problems = load_all()
        refresh_current()
        if problems:
            await app.push_screen_wait(TextDialog("Theme file problems", "\n".join(problems)))
        else:
            app.status.flash(f"Reloaded themes from {user_themes_dir()}.")

    @api.command("themes.folder", "Open T&hemes Folder", menu="view")
    def open_folder(app):
        from inkmill.system import open_folder as reveal

        folder = user_themes_dir()
        folder.mkdir(parents=True, exist_ok=True)
        try:
            reveal(folder)
            app.status.flash(f"Opened {folder}")
        except Exception:
            app.notify(f"Your themes folder is {folder}", timeout=10)

    # -- live editing ------------------------------------------------------------

    @api.on("document_saved")
    def saved(app, doc) -> None:
        if doc.path is None or doc.path.suffix.lower() != ".toml":
            return
        try:
            doc.path.resolve().relative_to(user_themes_dir().resolve())
        except ValueError:
            return
        try:
            info = loader.load_file(doc.path, "yours")
        except loader.ThemeFileError as exc:
            app.notify(str(exc), title="Theme not applied", severity="error", timeout=10)
            return
        add(info)
        if app.theme == info.theme.name:
            refresh_current()
        else:
            apply(info.theme.name)
        app.status.flash(f"Theme {info.label} applied.")

    @api.on("ready")
    def report(app) -> None:
        for problem in errors:
            app.notify(problem, title="Theme file skipped", severity="warning", timeout=10)
