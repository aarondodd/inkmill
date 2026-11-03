"""Finding notes for [[wikilinks]] and the links under the cursor. No UI code.

A note is any Markdown or text file under the project root, found by its
file name (without the extension) or by its front matter title, ignoring
case. The project root is the nearest folder above the document holding a
``.git`` folder or an ``.inkmill-root`` file, or else the document's own
folder and the one above it.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from inkmill import frontmatter

WIKILINK = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
MDLINK = re.compile(r"!?\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
URL = re.compile(r"\b(?:https?|ftp)://[^\s)>\]]+")
DOC_SUFFIXES = {".md", ".markdown", ".txt"}
SKIP_DIRS = {"node_modules", "__pycache__", ".snapshots", ".git", ".venv", "venv"}
LIMIT = 5000


def project_root(doc: Path) -> Path:
    folder = doc.resolve().parent
    home = Path.home().resolve()
    for candidate in [folder, *folder.parents]:
        if (candidate / ".git").exists() or (candidate / ".inkmill-root").exists():
            return candidate
        if candidate == home or candidate.parent == candidate:
            break
    return folder.parent if folder.parent != folder and folder != home else folder


@dataclass
class Index:
    root: Path
    by_name: dict[str, list[Path]] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)
    built: float = 0.0

    def build(self) -> "Index":
        self.by_name.clear()
        self.files.clear()
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
            for name in filenames:
                path = Path(dirpath) / name
                if path.suffix.lower() not in DOC_SUFFIXES:
                    continue
                self.files.append(path)
                self.by_name.setdefault(path.stem.lower(), []).append(path)
                title = _title(path)
                if title and title.lower() != path.stem.lower():
                    self.by_name.setdefault(title.lower(), []).append(path)
                if len(self.files) >= LIMIT:
                    break
            if len(self.files) >= LIMIT:
                break
        self.built = time.monotonic()
        return self

    def find(self, name: str, near: Path | None = None) -> Path | None:
        """The note called ``name``; the one nearest ``near`` if several share it."""
        key = name.strip().lower()
        if key.endswith((".md", ".markdown", ".txt")):
            key = key.rsplit(".", 1)[0]
        if "/" in key:  # a path relative to the root
            candidate = (self.root / name.strip()).resolve()
            for suffix in ("", ".md", ".markdown", ".txt"):
                path = candidate.with_name(candidate.name + suffix) if suffix else candidate
                if path.is_file():
                    return path
            key = key.rsplit("/", 1)[-1]
        matches = self.by_name.get(key, [])
        if not matches:
            return None
        if near is None or len(matches) == 1:
            return matches[0]
        base = near.resolve().parent
        return min(matches, key=lambda p: (len(os.path.relpath(p.parent, base).split(os.sep)), str(p)))


def _title(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(2048)
    except OSError:
        return ""
    value = frontmatter.read(head).get("title")
    return value.strip() if isinstance(value, str) else ""


@dataclass
class Link:
    kind: str  # "wiki", "file", "url", "anchor"
    target: str
    anchor: str = ""
    label: str = ""


def parse_wikilink(inner: str) -> Link:
    target, _, label = inner.partition("|")
    page, _, anchor = target.partition("#")
    return Link("wiki" if page.strip() else "anchor", page.strip(), anchor.strip(), label.strip())


def link_at(line: str, column: int) -> Link | None:
    """The link around ``column`` in ``line``: wikilink, Markdown link or URL."""
    for match in WIKILINK.finditer(line):
        if match.start() <= column <= match.end():
            return parse_wikilink(match.group(1))
    for match in MDLINK.finditer(line):
        if match.start() <= column <= match.end():
            target = match.group(1)
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                return Link("url", target)
            if target.startswith("#"):
                return Link("anchor", "", target[1:])
            path, _, anchor = target.partition("#")
            return Link("file", path, anchor)
    for match in URL.finditer(line):
        if match.start() <= column <= match.end():
            return Link("url", match.group().rstrip(".,;:"))
    return None


def heading_line(text: str, anchor: str) -> int | None:
    """Line of the heading matching ``anchor`` (its text or its slug)."""
    want = anchor.strip().lower()
    want_slug = slug(want)
    for i, line in enumerate(text.split("\n")):
        m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m and (m.group(1).strip().lower() == want or slug(m.group(1)) == want_slug):
            return i
    return None


def slug(text: str) -> str:
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def references(text: str, target: Path, names: set[str]) -> list[int]:
    """Line numbers in ``text`` that link to ``target`` by wikilink or Markdown link."""
    lines = []
    for i, line in enumerate(text.split("\n")):
        hit = False
        for m in WIKILINK.finditer(line):
            if parse_wikilink(m.group(1)).target.lower() in names:
                hit = True
        for m in MDLINK.finditer(line):
            if Path(m.group(1).split("#")[0]).name.lower() == target.name.lower():
                hit = True
        if hit:
            lines.append(i)
    return lines
