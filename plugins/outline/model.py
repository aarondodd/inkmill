"""Headings and sections of a Markdown document. No UI code.

A section is a heading plus everything up to the next heading of the same or
a higher level, so moving a section moves its subsections with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from inkmill.markup import mask_non_prose

ATX = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
SETEXT = re.compile(r"^(=+|-+)[ \t]*$")


@dataclass
class Heading:
    level: int
    title: str
    line: int
    setext: bool = False


def headings(text: str) -> list[Heading]:
    lines = text.split("\n")
    masked = mask_non_prose(text).split("\n")
    found: list[Heading] = []
    for i, line in enumerate(lines):
        if not masked[i].strip():
            continue  # inside front matter or a code block
        match = ATX.match(line)
        if match:
            found.append(Heading(len(match.group(1)), match.group(2).strip(), i))
            continue
        if i > 0 and SETEXT.match(line) and lines[i - 1].strip() and masked[i - 1].strip() and not ATX.match(lines[i - 1]):
            if found and found[-1].line == i - 1:
                continue
            level = 1 if line.lstrip().startswith("=") else 2
            if level == 2 and not lines[i - 1].strip():
                continue
            found.append(Heading(level, lines[i - 1].strip(), i - 1, setext=True))
    return found


def section(heads: list[Heading], index: int, line_count: int) -> tuple[int, int]:
    """[start, end) lines of the section starting at heading ``index``."""
    level = heads[index].level
    for later in heads[index + 1 :]:
        if later.level <= level:
            return heads[index].line, later.line
    return heads[index].line, line_count


def _sibling(heads: list[Heading], index: int, step: int) -> int | None:
    level = heads[index].level
    i = index + step
    while 0 <= i < len(heads):
        if heads[i].level < level:
            return None  # reached the parent: no sibling that way
        if heads[i].level == level:
            return i
        i += step
    return None


def move_section(text: str, index: int, step: int) -> tuple[str, int] | None:
    """Swap section ``index`` with its previous (-1) or next (+1) sibling.

    Returns the new text and the line the moved heading now starts on, or
    None when there is no sibling in that direction.
    """
    heads = headings(text)
    other = _sibling(heads, index, step)
    if other is None:
        return None
    lines = text.split("\n")
    first, second = (other, index) if step < 0 else (index, other)
    a_start, a_end = section(heads, first, len(lines))
    b_start, b_end = section(heads, second, len(lines))
    block_a, block_b = lines[a_start:a_end], lines[b_start:b_end]
    # Keep a blank line between the swapped sections.
    if block_b and block_b[-1].strip():
        block_b = block_b + [""]
    if block_a and not block_a[-1].strip() and b_end == len(lines):
        while block_a and not block_a[-1].strip():
            block_a = block_a[:-1]
    new_lines = lines[:a_start] + block_b + lines[a_end:b_start] + block_a + lines[b_end:]
    moved_line = a_start if step < 0 else a_start + len(block_b) + (b_start - a_end)
    return "\n".join(new_lines), moved_line


def shift_level(text: str, index: int, delta: int) -> str | None:
    """Promote (-1) or demote (+1) a heading and every heading in its section."""
    heads = headings(text)
    lines = text.split("\n")
    start, end = section(heads, index, len(lines))
    targets = [h for h in heads if start <= h.line < end]
    if any(not 1 <= h.level + delta <= 6 for h in targets):
        return None
    for h in targets:
        if h.setext:
            lines[h.line] = "#" * (h.level + delta) + " " + h.title
            lines[h.line + 1] = None  # type: ignore[call-overload]
        else:
            lines[h.line] = "#" * (h.level + delta) + lines[h.line].lstrip("#")
    return "\n".join(line for line in lines if line is not None)
