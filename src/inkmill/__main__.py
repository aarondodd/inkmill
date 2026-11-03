"""Command line entry point: ``inkmill [files...]``."""

from __future__ import annotations

import argparse
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
            return app.return_code or 0
        purge_plugin_modules()


if __name__ == "__main__":
    sys.exit(main())
