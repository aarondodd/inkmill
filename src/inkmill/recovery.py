"""Crash recovery snapshots of unsaved documents.

While a document has unsaved changes, its text is copied to the state
directory every ``recovery_interval`` seconds. Saving or closing the document
cleanly removes the snapshot, so anything left over at startup is work a crash
or a killed terminal would otherwise have lost.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .documents import Document


@dataclass
class Snapshot:
    key: str
    title: str
    path: str | None
    format: str
    saved_at: float
    text_file: Path

    def read(self) -> str:
        return self.text_file.read_text(encoding="utf-8")


class RecoveryStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._last: dict[str, str] = {}

    def snapshot(self, doc: "Document") -> bool:
        key = doc.recovery_key
        if self._last.get(key) == doc.text:
            return False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / f"{key}.txt").write_text(doc.text, encoding="utf-8")
            meta = {
                "title": doc.title,
                "path": str(doc.path) if doc.path else None,
                "format": doc.format.id,
                "saved_at": time.time(),
            }
            (self.directory / f"{key}.json").write_text(json.dumps(meta), encoding="utf-8")
        except OSError:
            return False
        self._last[key] = doc.text
        return True

    def clear(self, doc: "Document") -> None:
        self.discard(doc.recovery_key)

    def discard(self, key: str) -> None:
        self._last.pop(key, None)
        for suffix in (".txt", ".json"):
            try:
                (self.directory / f"{key}{suffix}").unlink()
            except OSError:
                pass

    def list(self) -> list[Snapshot]:
        if not self.directory.is_dir():
            return []
        out = []
        for meta_file in self.directory.glob("*.json"):
            text_file = meta_file.with_suffix(".txt")
            if not text_file.exists():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out.append(
                Snapshot(
                    key=meta_file.stem,
                    title=str(meta.get("title", meta_file.stem)),
                    path=meta.get("path"),
                    format=str(meta.get("format", "markdown")),
                    saved_at=float(meta.get("saved_at", 0)),
                    text_file=text_file,
                )
            )
        return sorted(out, key=lambda s: -s.saved_at)
