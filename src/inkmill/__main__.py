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

    from .app import InkmillApp

    app = InkmillApp(args.files, load_plugins=not args.no_plugins)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
