"""Document links kept in front matter, with no UI code.

A document may name, relative to its own folder:

    parent:   the binder (overall document) it belongs to; one or a list
    previous: the document before it
    next:     the document after it
    related:  a list of documents it relates to
    contents: for a binder, its documents in reading order
    research: for a binder, notes, folders, files and web addresses that
              support the work but are not part of the manuscript

Chapters can also carry ``status`` (draft, revised, ...), ``synopsis`` and a
word ``target``; a binder can carry a ``target`` and a ``deadline``.

Order normally lives in the binder's ``contents``, so a chapter only needs
``parent`` and its neighbors are worked out from the list. Explicit
``previous`` and ``next`` win when present, which is how two documents link
without a binder at all.

``up`` and ``prev`` are read as aliases of ``parent`` and ``previous``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from inkmill import frontmatter as fm
from inkmill.documents import count_words

ReadFn = Callable[[Path], "str | None"]

ALIASES = {"parent": ("parent", "up"), "previous": ("previous", "prev"), "next": ("next",), "related": ("related",),
           "contents": ("contents",), "research": ("research",)}
RELATIONS = ("parent", "previous", "next", "related", "contents", "research")
LIST_RELATIONS = {"parent", "related", "contents", "research"}
STATUSES = ("idea", "outline", "draft", "revised", "final")
URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
DOC_SUFFIXES = (".md", ".markdown", ".txt")
SCAN_LIMIT = 400

_HEADING = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)
_NUMBER = re.compile(r"^(.*?)(\d+)(\D*)$")
_FOOTNOTE = re.compile(r"\[\^([^\]\s]+)\]")


def norm(path: Path) -> Path:
    return Path(os.path.normpath(os.path.abspath(path)))


def same(a: Path | None, b: Path | None) -> bool:
    if a is None or b is None:
        return False
    return os.path.normcase(str(norm(a))) == os.path.normcase(str(norm(b)))


def resolve(owner: Path, ref: str) -> Path:
    """Path a reference in ``owner``'s front matter points to."""
    target = Path(os.path.expanduser(ref.strip()))
    if not target.is_absolute():
        target = owner.parent / target
    return norm(target)


def relref(owner: Path, target: Path) -> str:
    """How ``owner`` should refer to ``target``: relative, forward slashes."""
    try:
        rel = os.path.relpath(norm(target), norm(owner).parent)
    except ValueError:  # different drives on Windows
        return norm(target).as_posix()
    return rel.replace(os.sep, "/")


@dataclass
class Links:
    owner: Path
    parents: list[Path] = field(default_factory=list)
    previous: Path | None = None
    next: Path | None = None
    related: list[Path] = field(default_factory=list)
    contents: list[Path] = field(default_factory=list)
    research: list[Path] = field(default_factory=list)
    research_urls: list[str] = field(default_factory=list)
    title: str = ""

    @property
    def is_binder(self) -> bool:
        return bool(self.contents)

    def all(self) -> list[tuple[str, Path]]:
        out = [("parent", p) for p in self.parents]
        if self.previous:
            out.append(("previous", self.previous))
        if self.next:
            out.append(("next", self.next))
        out += [("related", p) for p in self.related]
        out += [("contents", p) for p in self.contents]
        out += [("research", p) for p in self.research]
        return out


def _get(meta: dict, relation: str) -> list[str]:
    for key in ALIASES[relation]:
        if key in meta:
            return fm.as_list(meta[key])
    return []


def key_in(meta: dict, relation: str) -> str:
    """The spelling this document already uses for a relation, or the canonical one."""
    for key in ALIASES[relation]:
        if key in meta:
            return key
    return relation


def title_of(path: Path, text: str | None) -> str:
    if text:
        meta = fm.read(text)
        title = meta.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        _, body = fm.split(text)
        match = _HEADING.search(body)
        if match:
            return match.group(1).strip()
    return path.stem.replace("-", " ").replace("_", " ")


def read_links(owner: Path, text: str | None) -> Links:
    meta = fm.read(text or "")
    links = Links(owner=norm(owner), title=title_of(owner, text))
    links.parents = [resolve(owner, r) for r in _get(meta, "parent")]
    prev = _get(meta, "previous")
    nxt = _get(meta, "next")
    links.previous = resolve(owner, prev[0]) if prev else None
    links.next = resolve(owner, nxt[0]) if nxt else None
    links.related = [resolve(owner, r) for r in _get(meta, "related")]
    links.contents = [resolve(owner, r) for r in _get(meta, "contents")]
    for ref in _get(meta, "research"):
        if URL.match(ref.strip()):
            links.research_urls.append(ref.strip())
        else:
            links.research.append(resolve(owner, ref))
    return links


def field_value(text: str | None, key: str) -> str:
    value = fm.read(text or "").get(key, "")
    return value if isinstance(value, str) else ", ".join(value)


def set_field(text: str, key: str, value: str | None) -> str:
    return fm.update(text, {key: value if value else None})


@dataclass
class Position:
    """Where a document sits: its binder (if any) and its neighbors."""

    binder: Path | None = None
    binder_links: Links | None = None
    index: int = -1  # zero based, -1 when not in the binder's contents
    previous: Path | None = None
    next: Path | None = None

    @property
    def total(self) -> int:
        return len(self.binder_links.contents) if self.binder_links else 0


def position(links: Links, read: ReadFn) -> Position:
    pos = Position()
    for parent in links.parents:
        parent_links = read_links(parent, read(parent))
        if pos.binder is None:
            pos.binder, pos.binder_links = parent, parent_links
        for i, item in enumerate(parent_links.contents):
            if same(item, links.owner):
                pos.binder, pos.binder_links, pos.index = parent, parent_links, i
                if i > 0:
                    pos.previous = parent_links.contents[i - 1]
                if i + 1 < len(parent_links.contents):
                    pos.next = parent_links.contents[i + 1]
                break
        if pos.index >= 0:
            break
    if links.previous:
        pos.previous = links.previous
    if links.next:
        pos.next = links.next
    return pos


def backlinks(owner: Path, read: ReadFn, folders: Iterable[Path] | None = None) -> list[tuple[str, Path]]:
    """Documents near ``owner`` whose front matter points at it.

    Looks in the document's own folder, the folder above and the folders
    directly below, which is where a binder and its chapters normally sit.
    """
    owner = norm(owner)
    if folders is None:
        folders = [owner.parent, owner.parent.parent]
        try:
            folders += sorted(p for p in owner.parent.iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError:
            pass
    folders = list(folders)
    seen: set[str] = set()
    found: list[tuple[str, Path]] = []
    scanned = 0
    for folder in folders:
        try:
            candidates = sorted(p for p in folder.iterdir() if p.suffix.lower() in DOC_SUFFIXES and p.is_file())
        except OSError:
            continue
        for path in candidates:
            key = os.path.normcase(str(norm(path)))
            if key in seen or same(path, owner):
                continue
            seen.add(key)
            scanned += 1
            if scanned > SCAN_LIMIT:
                return found
            other = read_links(path, read(path))
            for relation, target in other.all():
                if same(target, owner):
                    found.append((relation, norm(path)))
    return found


def next_name(path: Path) -> str:
    """``chapter-02.md`` -> ``chapter-03.md``; otherwise ``<stem>-next.md``."""
    match = _NUMBER.match(path.stem)
    if match:
        prefix, number, suffix = match.groups()
        return f"{prefix}{int(number) + 1:0{len(number)}d}{suffix}{path.suffix}"
    return f"{path.stem}-next{path.suffix or '.md'}"


def set_relation(text: str, owner: Path, relation: str, targets: list) -> str:
    """Rewrite one relation in ``text``. An empty list removes the key.

    Targets are paths, or strings (web addresses) kept as written.
    """
    meta = fm.read(text)
    key = key_in(meta, relation)
    refs = [t if isinstance(t, str) else relref(owner, t) for t in targets]
    if not refs:
        value = None
    elif relation in LIST_RELATIONS and (relation != "parent" or len(refs) > 1):
        value = refs
    else:
        value = refs[0]
    return fm.update(text, {key: value})


def add_relation(text: str, owner: Path, relation: str, target, *, after: Path | None = None) -> str:
    links = read_links(owner, text)
    if relation == "research":
        current = [*links.research, *links.research_urls]
        if isinstance(target, str):
            if target in links.research_urls:
                return text
            return set_relation(text, owner, relation, current + [target])
    else:
        current = {"parent": links.parents, "related": links.related, "contents": links.contents}.get(relation)
    if current is None:
        return set_relation(text, owner, relation, [target])
    if any(not isinstance(t, str) and same(t, target) for t in current):
        return text
    items = list(current)
    index = len(items)
    if after is not None:
        for i, item in enumerate(items):
            if same(item, after):
                index = i + 1
                break
    items.insert(index, target if isinstance(target, str) else norm(target))
    return set_relation(text, owner, relation, items)


def remove_relation(text: str, owner: Path, relation: str, target) -> str:
    links = read_links(owner, text)
    current = {
        "parent": links.parents,
        "related": links.related,
        "contents": links.contents,
        "research": [*links.research, *links.research_urls],
        "previous": [links.previous] if links.previous else [],
        "next": [links.next] if links.next else [],
    }[relation]
    remaining = [t for t in current if (t != target if isinstance(t, str) or isinstance(target, str) else not same(t, target))]
    if len(remaining) == len(current):
        return text
    return set_relation(text, owner, relation, remaining)


def move_in_contents(text: str, owner: Path, target: Path, step: int) -> str:
    links = read_links(owner, text)
    items = list(links.contents)
    for i, item in enumerate(items):
        if same(item, target):
            j = i + step
            if 0 <= j < len(items):
                items[i], items[j] = items[j], items[i]
                return set_relation(text, owner, "contents", items)
            break
    return text


def rewrite_target(text: str, owner: Path, old: Path, new: Path) -> str:
    """Point every reference to ``old`` in ``owner`` at ``new`` instead."""
    links = read_links(owner, text)
    for relation, items in (
        ("parent", links.parents),
        ("related", links.related),
        ("contents", links.contents),
        ("research", [*links.research, *links.research_urls]),
        ("previous", [links.previous] if links.previous else []),
        ("next", [links.next] if links.next else []),
    ):
        if any(not isinstance(t, str) and same(t, old) for t in items):
            text = set_relation(text, owner, relation, [new if not isinstance(t, str) and same(t, old) else t for t in items])
    return text


def rebase(text: str, old_owner: Path, new_owner: Path) -> str:
    """Keep a moved document's own relative references pointing at the same files."""
    links = read_links(old_owner, text)
    for relation, items in (
        ("parent", links.parents),
        ("related", links.related),
        ("contents", links.contents),
        ("research", [*links.research, *links.research_urls]),
        ("previous", [links.previous] if links.previous else []),
        ("next", [links.next] if links.next else []),
    ):
        if items:
            text = set_relation(text, new_owner, relation, items)
    return text


def leaves(binder: Path, read: ReadFn, *, seen: set[str] | None = None) -> list[Path]:
    """The documents of a binder in reading order, descending into sub-binders."""
    seen = seen if seen is not None else set()
    key = os.path.normcase(str(norm(binder)))
    if key in seen:
        return []
    seen.add(key)
    out: list[Path] = []
    for item in read_links(binder, read(binder)).contents:
        child = read_links(item, read(item))
        if child.contents:
            out.extend(leaves(item, read, seen=seen))
        else:
            out.append(item)
    return out


def binder_words(binder: Path, read: ReadFn) -> int:
    return sum(count_words(read(p) or "") for p in leaves(binder, read))


def manuscript_markdown(binder: Path, read: ReadFn, *, include_binder_text: bool = False, add_titles: bool = True) -> str:
    """One Markdown document made of every chapter in the binder.

    Footnote labels are prefixed per chapter so ``[^1]`` in chapter one and
    ``[^1]`` in chapter two stay separate notes.
    """
    binder_text = read(binder) or ""
    lines, binder_body = fm.split(binder_text)
    meta = fm.parse(lines) if lines is not None else {}
    head = {k: v for k, v in meta.items() if k in ("title", "author", "date", "description", "lang") and isinstance(v, str)}
    if "title" not in head:
        head["title"] = title_of(binder, binder_text)
    parts: list[str] = []
    if include_binder_text and binder_body.strip():
        parts.append(binder_body.strip())
    for n, path in enumerate(leaves(binder, read), start=1):
        text = read(path)
        if text is None:
            parts.append(f"> [!WARNING]\n> Missing: {path.name}")
            continue
        _, body = fm.split(text)
        body = _FOOTNOTE.sub(lambda m, n=n: f"[^c{n}-{m.group(1)}]", body).strip()
        if add_titles and not body.lstrip().startswith("#"):
            body = f"# {title_of(path, text)}\n\n{body}"
        parts.append(body)
    front = fm.update("", {k: v for k, v in head.items()})
    separator = '\n\n<div class="inkmill-page-break" style="break-before: page"></div>\n\n'
    return front + "\n" + separator.join(parts) + "\n"


def broken(owner: Path, text: str | None) -> list[tuple[str, Path]]:
    return [(rel, target) for rel, target in read_links(owner, text).all() if not target.exists()]
