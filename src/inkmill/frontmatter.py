"""Read and edit YAML front matter without disturbing the rest of it.

Inkmill does not depend on a YAML library. The reader understands the subset
that writers and tools actually put in front matter: ``key: value`` scalars
(quoted or not), flow lists (``key: [a, b]``) and block lists::

    related:
      - notes/characters.md
      - research/ships.md

The writer changes only the keys it is asked to change. Every other line,
including comments, key order and nested structures it does not understand,
is kept exactly as it was.
"""

from __future__ import annotations

import re
from typing import Union

Value = Union[str, list[str]]

_KEY = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*)\s*:(?:\s+(.*?))?\s*$")
_ITEM = re.compile(r"^\s+-\s+(.*?)\s*$|^\s+-\s*$")


def split(text: str) -> tuple[list[str] | None, str]:
    """Return (front matter lines without the fences, body).

    Returns ``(None, text)`` when the text has no front matter block.
    """
    if not text.startswith("---\n") and text != "---":
        return None, text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].rstrip() in ("---", "..."):
            return lines[1:i], "\n".join(lines[i + 1 :])
    return None, text


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner
    # A trailing comment after a plain scalar.
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _split_flow(inner: str) -> list[str]:
    items: list[str] = []
    current = ""
    quote = ""
    for ch in inner:
        if quote:
            current += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            current += ch
        elif ch == ",":
            items.append(current)
            current = ""
        else:
            current += ch
    if current.strip():
        items.append(current)
    return [_unquote(i) for i in items if i.strip()]


def _parse_value(raw: str) -> Value:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return _split_flow(raw[1:-1])
    return _unquote(raw)


def _spans(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Map each top-level key to the [start, end) line range it occupies."""
    spans: dict[str, tuple[int, int]] = {}
    current: str | None = None
    start = 0
    for i, line in enumerate(lines):
        match = _KEY.match(line)
        if match and not line[:1].isspace():
            if current is not None:
                spans[current] = (start, i)
            current, start = match.group(1), i
        elif line and not line[:1].isspace() and not line.startswith("#"):
            if current is not None:
                spans[current] = (start, i)
            current = None
    if current is not None:
        spans[current] = (start, len(lines))
    return spans


def parse(lines: list[str]) -> dict[str, Value]:
    meta: dict[str, Value] = {}
    for key, (start, end) in _spans(lines).items():
        match = _KEY.match(lines[start])
        assert match is not None
        inline = match.group(2) or ""
        if inline:
            meta[key] = _parse_value(inline)
            continue
        items = []
        for line in lines[start + 1 : end]:
            item = _ITEM.match(line)
            if item:
                items.append(_unquote(item.group(1) or ""))
        meta[key] = items if items else ""
    return meta


def read(text: str) -> dict[str, Value]:
    """Front matter of ``text`` as a dict. Keys keep their spelling."""
    lines, _ = split(text)
    return parse(lines) if lines is not None else {}


def _quote(value: str) -> str:
    if value == "" or re.search(r"^[\s\-?:,\[\]{}#&*!|>'\"%@`]|:\s|\s#|\s$", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _render(key: str, value: Value) -> list[str]:
    if isinstance(value, list):
        if not value:
            return [f"{key}: []"]
        flow = f"{key}: [" + ", ".join(_quote(v) for v in value) + "]"
        if len(value) <= 2 and len(flow) <= 72 and not any("," in v for v in value):
            return [flow]
        return [f"{key}:"] + [f"  - {_quote(v)}" for v in value]
    return [f"{key}: {_quote(value)}"]


def update(text: str, changes: dict[str, Value | None]) -> str:
    """Return ``text`` with the given keys set, or removed when the value is None.

    New keys are appended to the end of the block. A document without front
    matter gains a block when there is anything to write.
    """
    lines, body = split(text)
    if lines is None:
        additions = [line for key, value in changes.items() if value is not None for line in _render(key, value)]
        if not additions:
            return text
        return "---\n" + "\n".join(additions) + "\n---\n" + text
    lines = list(lines)
    spans = _spans(lines)
    # Replace from the bottom up so earlier spans stay valid.
    for key in sorted((k for k in changes if k in spans), key=lambda k: spans[k][0], reverse=True):
        start, end = spans[key]
        # Keep trailing blank or comment lines that belong to the next key.
        while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
            end -= 1
        value = changes[key]
        lines[start:end] = [] if value is None else _render(key, value)
    for key, value in changes.items():
        if key not in spans and value is not None:
            lines.extend(_render(key, value))
    if not any(line.strip() for line in lines):
        return body
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def as_list(value: Value | None) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [v for v in value if v]
    return [value]
