"""Exporters turn a document into another file format.

HTML is built in. Plugins can register more (EPUB, ODT, PDF via an external
tool) by registering an :class:`Exporter` with the app's ``exporters`` registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..config import Settings
    from ..documents import Document

ExportFunc = Callable[["Document", "Settings"], str | bytes]


@dataclass
class Exporter:
    id: str
    name: str
    extension: str
    export: ExportFunc

    def write(self, doc: "Document", settings: "Settings", target: Path) -> Path:
        data = self.export(doc, settings)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            target.write_bytes(data)
        else:
            target.write_text(data, encoding="utf-8")
        return target


class ExporterRegistry:
    def __init__(self) -> None:
        self._exporters: dict[str, Exporter] = {}

    def register(self, exporter: Exporter) -> Exporter:
        self._exporters[exporter.id] = exporter
        return exporter

    def get(self, id: str) -> Exporter | None:
        return self._exporters.get(id)

    def __iter__(self):
        return iter(self._exporters.values())


def builtin_exporters() -> ExporterRegistry:
    from .html import export_html

    registry = ExporterRegistry()
    registry.register(Exporter("html", "HTML web page", ".html", export_html))
    return registry
