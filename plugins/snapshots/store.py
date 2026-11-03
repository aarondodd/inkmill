"""Snapshot storage and comparison. No UI code.

Snapshots live in the state folder by default, one folder per document keyed
by its path, so they never land in a git repository by accident. With
``location = "beside"`` they go in a ``.snapshots`` folder next to the
document instead, which travels with the project.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text

from inkmill.documents import count_words


@dataclass
class Snapshot:
    file: str
    name: str
    taken: float
    words: int
    folder: Path

    @property
    def path(self) -> Path:
        return self.folder / self.file

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def when(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.taken))


class Store:
    def __init__(self, doc_path: Path, root: Path, *, beside: bool = False) -> None:
        doc_path = doc_path.resolve()
        if beside:
            self.folder = doc_path.parent / ".snapshots" / doc_path.name
        else:
            key = hashlib.sha1(str(doc_path).encode("utf-8")).hexdigest()[:16]
            self.folder = root / key
        self.doc_path = doc_path
        self.index = self.folder / "index.json"

    def _load(self) -> dict:
        try:
            data = json.loads(self.index.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("snapshots"), list):
                return data
        except (OSError, ValueError):
            pass
        return {"path": str(self.doc_path), "snapshots": []}

    def list(self) -> list[Snapshot]:
        items = []
        for item in self._load()["snapshots"]:
            snap = Snapshot(item["file"], item.get("name", ""), float(item["taken"]), int(item.get("words", 0)), self.folder)
            if snap.path.exists():
                items.append(snap)
        return sorted(items, key=lambda s: s.taken, reverse=True)

    def take(self, text: str, name: str = "") -> Snapshot:
        self.folder.mkdir(parents=True, exist_ok=True)
        taken = time.time()
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(taken))
        file = f"{stamp}{self.doc_path.suffix or '.md'}"
        n = 2
        while (self.folder / file).exists():
            file = f"{stamp}-{n}{self.doc_path.suffix or '.md'}"
            n += 1
        (self.folder / file).write_text(text, encoding="utf-8")
        data = self._load()
        data["path"] = str(self.doc_path)
        data["snapshots"].append({"file": file, "name": name, "taken": taken, "words": count_words(text)})
        self._write(data)
        return Snapshot(file, name, taken, count_words(text), self.folder)

    def delete(self, snap: Snapshot) -> None:
        snap.path.unlink(missing_ok=True)
        data = self._load()
        data["snapshots"] = [s for s in data["snapshots"] if s["file"] != snap.file]
        self._write(data)

    def rename(self, snap: Snapshot, name: str) -> None:
        data = self._load()
        for item in data["snapshots"]:
            if item["file"] == snap.file:
                item["name"] = name
        self._write(data)

    def _write(self, data: dict) -> None:
        tmp = self.index.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self.index)


_TOKEN = re.compile(r"\s+|[^\s]+")


def compare(old: str, new: str, *, context: int = 1) -> Text:
    """A readable comparison: changed paragraphs with word-level marks.

    Removed words are struck through, added words are underlined and bold,
    and unchanged paragraphs between changes are summarized.
    """
    old_lines, new_lines = old.split("\n"), new.split("\n")
    out = Text()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    groups = matcher.get_grouped_opcodes(context)
    any_change = False
    for group in groups:
        any_change = True
        first = group[0]
        out.append(f"\n@ line {first[3] + 1}\n", style="dim")
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for line in new_lines[j1:j2]:
                    out.append("  " + line + "\n", style="dim")
            elif tag == "replace" and (i2 - i1) == (j2 - j1):
                for a, b in zip(old_lines[i1:i2], new_lines[j1:j2]):
                    out.append("~ ")
                    _words(out, a, b)
                    out.append("\n")
            else:
                for line in old_lines[i1:i2]:
                    out.append("- " + line + "\n", style="strike")
                for line in new_lines[j1:j2]:
                    out.append("+ " + line + "\n", style="bold underline")
    if not any_change:
        out.append("No differences.")
    return out


def _words(out: Text, a: str, b: str) -> None:
    ta, tb = _TOKEN.findall(a), _TOKEN.findall(b)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ta, b=tb, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append("".join(tb[j1:j2]))
        else:
            if i2 > i1:
                out.append("".join(ta[i1:i2]), style="strike")
            if j2 > j1:
                out.append("".join(tb[j1:j2]), style="bold underline")
