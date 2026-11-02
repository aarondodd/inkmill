"""Document formats.

A format knows how to turn a file on disk into editor text and back. The editor
always works on plain text; richer formats (a future .docx or .odt importer,
for example) convert to and from Markdown at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

Loader = Callable[[Path], str]
Saver = Callable[[Path, str], None]


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1")
    # Normalize Windows and old Mac line endings; the editor works in "\n".
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.inkmill-tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        if text and not text.endswith("\n"):
            fh.write("\n")
    tmp.replace(path)


@dataclass
class DocumentFormat:
    id: str
    name: str
    extensions: tuple[str, ...]
    # tree-sitter language name for editor highlighting, if any.
    language: str | None = None
    load: Loader = read_text
    save: Saver = write_text
    # Whether the HTML exporter understands this format's text.
    markdown: bool = False

    @property
    def default_extension(self) -> str:
        return self.extensions[0]


class FormatRegistry:
    def __init__(self) -> None:
        self._formats: dict[str, DocumentFormat] = {}

    def register(self, fmt: DocumentFormat) -> DocumentFormat:
        self._formats[fmt.id] = fmt
        return fmt

    def get(self, id: str) -> DocumentFormat | None:
        return self._formats.get(id)

    def __iter__(self):
        return iter(self._formats.values())

    def for_path(self, path: Path, default: str = "markdown") -> DocumentFormat:
        suffix = path.suffix.lower()
        for fmt in self._formats.values():
            if suffix in fmt.extensions:
                return fmt
        return self._formats.get("text") or self._formats[default]

    def document_extensions(self) -> set[str]:
        return {ext for fmt in self._formats.values() for ext in fmt.extensions}


MARKDOWN = DocumentFormat(
    id="markdown",
    name="Markdown",
    extensions=(".md", ".markdown", ".mdown", ".mkd", ".mdx"),
    language="markdown",
    markdown=True,
)

TEXT = DocumentFormat(
    id="text",
    name="Plain text",
    extensions=(".txt", ".text"),
)


def builtin_formats() -> FormatRegistry:
    registry = FormatRegistry()
    registry.register(MARKDOWN)
    registry.register(TEXT)
    return registry
