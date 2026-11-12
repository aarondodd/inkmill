"""Command line entry point: ``inkmill [files...]``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import APP_NAME, __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inkmill",
        description=f"{APP_NAME}: a distraction-free terminal word processor for Markdown.",
    )
    parser.add_argument("files", nargs="*", type=Path, help="documents to open")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--export", metavar="FILE", type=Path, help="export FILE to HTML and exit")
    parser.add_argument("-o", "--output", type=Path, help="output path for --export (default: FILE.html)")
    parser.add_argument("--style", help="HTML style for --export (see --list-styles)")
    parser.add_argument("--list-styles", action="store_true", help="list HTML export styles and exit")
    parser.add_argument("--paths", action="store_true", help="show settings, plugin and state locations and exit")
    parser.add_argument("--plugins", action="store_true", help="list plugins and whether they load, then exit")
    parser.add_argument("--no-plugins", action="store_true", help="start without loading plugins")
    parser.add_argument("--check-update", action="store_true", help="say whether a newer Inkmill is out, then exit")
    parser.add_argument("--update", action="store_true", help="install a newer Inkmill if there is one, then exit")
    parser.add_argument(
        "--import-conversation", metavar="FOLDER", type=Path,
        help="copy a project's earlier AI conversation into the record Inkmill keeps in FOLDER, then exit "
             "(needs the AI Assistant plugin)",
    )
    parser.add_argument(
        "--from", dest="import_from", metavar="SOURCE", default="",
        help="for --import-conversation: 'all' (every Claude Code conversation started in FOLDER), a Claude "
             "Code session id or .jsonl file, or a conversation note saved by the AI Assistant (.md); "
             "default: the Claude Code conversation Inkmill uses for FOLDER",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.paths:
        from .config import Settings, config_dir, state_dir

        print(f"settings: {Settings.path()}")
        print(f"styles:   {config_dir() / 'styles'}")
        print(f"plugins:  {config_dir() / 'plugins'}")
        print(f"state:    {state_dir()}")
        return 0

    if args.plugins:
        from .plugins import describe_requirement, discover, is_compatible

        for item in discover():
            version = f" {item.manifest.version}" if item.manifest else ""
            note = ""
            if item.error:
                note = f"  (error: {item.error})"
            elif item.manifest and not is_compatible(item.manifest.requires_inkmill):
                note = f"  (needs {describe_requirement(item.manifest.requires_inkmill)})"
            print(f"{item.name}{version}  {item.source}{note}")
            for req in item.manifest.requires if item.manifest else []:
                if req.found() is None:
                    kind = "optional" if req.optional else "required"
                    hint = req.install_hint()
                    print(f"    missing {kind} program {req.name}" + (f"; install: {hint}" if hint else ""))
        return 0

    if args.import_conversation:
        return import_conversation(args.import_conversation, args.import_from)

    if args.check_update or args.update:
        return update_from_command_line(install=args.update)

    if args.list_styles:
        from .export.html import available_styles

        for name in available_styles():
            print(name)
        return 0

    if args.export:
        from .config import Settings
        from .documents import Document
        from .export import builtin_exporters
        from .formats import builtin_formats

        source: Path = args.export
        if not source.is_file():
            print(f"inkmill: {source}: no such file", file=sys.stderr)
            return 2
        settings = Settings.load()
        if args.style:
            settings.export_style = args.style
        doc = Document.from_file(source, builtin_formats().for_path(source))
        target = args.output or source.with_suffix(".html")
        builtin_exporters().get("html").write(doc, settings, target)  # type: ignore[union-attr]
        print(target)
        return 0

    return run_app(args.files, load_plugins=not args.no_plugins)


def import_conversation(folder: Path, source: str) -> int:
    """Hand ``--import-conversation`` to the AI Assistant plugin, wherever it is installed."""
    from .plugins import discover

    item = next((f for f in discover() if f.name == "ai"), None)
    if item is None or item.error:
        print("inkmill: --import-conversation needs the AI Assistant plugin; install it with Plugins > Manage Plugins",
              file=sys.stderr)
        return 2
    try:
        module = item.loader()
    except Exception as exc:  # a broken plugin should not show a traceback here
        print(f"inkmill: the AI Assistant plugin did not load: {exc}", file=sys.stderr)
        return 2
    run = getattr(module, "import_conversation", None)
    if run is None:
        print("inkmill: this AI Assistant plugin is too old for --import-conversation; update it in Plugins > Manage Plugins",
              file=sys.stderr)
        return 2
    try:
        for line in run(folder, source):
            print(line)
    except (OSError, ValueError) as exc:
        print(f"inkmill: {exc}", file=sys.stderr)
        return 1
    return 0


def update_from_command_line(*, install: bool) -> int:
    from . import updates
    from .config import Settings

    try:
        release = updates.fetch_release(updates.source_url(Settings.load().updates))
    except updates.UpdateError as exc:
        print(f"inkmill: could not check for updates: {exc}", file=sys.stderr)
        return 1
    method = updates.detect()
    if not install or not release.newer_than():
        print(updates.describe(release, method))
        return 0
    if method.automatic:
        print(f"Installing Inkmill {release.version} with {method.label}...")
        try:
            updates.install(method)
        except updates.UpdateError as exc:
            print(f"inkmill: {exc}", file=sys.stderr)
            print("To update by hand, run:\n" + "\n".join(f"  {line}" for line in method.manual), file=sys.stderr)
            return 1
        installed = updates.installed_version()
        if not updates.is_newer(installed, __version__):
            print(f"inkmill: the update command finished, but {installed or 'an unknown version'} is still installed", file=sys.stderr)
            return 1
        print(f"Inkmill {installed} is installed.")
        return 0
    if method.deferred:
        try:
            updates.start_deferred(method)
        except updates.UpdateError as exc:
            print(f"inkmill: {exc}", file=sys.stderr)
            return 1
        print(f"Inkmill {release.version} is being installed in a new window.")
        return 0
    print(f"Inkmill {release.version} is available. {method.reason}\nTo update, run:")
    print("\n".join(f"  {line}" for line in method.manual))
    return 1


def after_exit(app, load_plugins: bool) -> None:
    """Run what the update commands asked for once the app has closed."""
    from . import updates

    if app.pending_update is not None:
        try:
            updates.start_deferred(app.pending_update)
            print("Inkmill is being updated in a new window.")
        except updates.UpdateError as exc:
            print(f"inkmill: {exc}", file=sys.stderr)
            print("To update by hand, run:\n" + "\n".join(f"  {line}" for line in app.pending_update.manual), file=sys.stderr)
    elif app.after_exit == "restart":
        # A new process, because the running one still holds the old modules.
        argv = [sys.executable, "-m", "inkmill"]
        if not load_plugins:
            argv.append("--no-plugins")
        argv += app.state.session
        sys.stdout.flush()
        os.execv(sys.executable, argv)


def run_app(files: list[Path], *, load_plugins: bool = True) -> int:
    """Run Inkmill, starting it again in place whenever it asks to restart.

    A restart (after installing or updating plugins) keeps the same Python
    process: plugin modules are dropped from ``sys.modules`` and a new app
    receives the open documents, unsaved text included. That works the same
    way on Windows, Linux and Termux, where replacing the process would not.
    """
    from .app import InkmillApp
    from .plugins import purge_plugin_modules

    handoff = None
    while True:
        app = InkmillApp(files if handoff is None else (), load_plugins=load_plugins, handoff=handoff)
        app.run()
        handoff = app.restart_handoff
        if handoff is None:
            after_exit(app, load_plugins)
            return app.return_code or 0
        purge_plugin_modules()


if __name__ == "__main__":
    sys.exit(main())
