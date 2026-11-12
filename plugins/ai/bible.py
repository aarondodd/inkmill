"""Updating the story bible from a conversation: the request, reading the
suggested entries back, and filing accepted ones under the bible's own
headings. No UI code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

DEFAULT_SECTIONS = ["Characters", "Places", "Timeline", "Style"]
_HEADING = re.compile(r"^##\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")

REQUEST = (
    "{conversation} The story bible{bible} holds the facts the writer has already settled.\n\n"
    "List the facts that conversation settled which the story bible does not already hold: about the "
    "characters, places, timeline, plot and style. Leave out ideas the writer rejected or left undecided, "
    "questions, and anything the bible already says. Where the conversation changed something the bible "
    "says, include the new fact and say in the note what it contradicts.\n\n"
    "Reply with only a JSON array and no other text. Each item is an object with \"section\" (one of the "
    "bible's headings: {sections}; or a short new heading if none fits), \"entry\" (the fact, one or two "
    "plain sentences ready to go in the bible) and \"note\" (empty, or what in the bible it contradicts). "
    "Reply [] if there is nothing new."
)


@dataclass
class Proposal:
    section: str
    entry: str
    note: str = ""


def sections(text: str) -> list[str]:
    """The bible's level-2 headings, outside code blocks."""
    out, fence = [], None
    for line in text.splitlines():
        m = _FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        h = _HEADING.match(line)
        if h:
            out.append(h.group(1).strip())
    return out


def request(conversation: str, bible: str, headings: list[str]) -> str:
    """The prompt; ``conversation`` and ``bible`` say where each is (a sentence naming a
    file, or the text itself)."""
    names = ", ".join(headings or DEFAULT_SECTIONS)
    return REQUEST.format(conversation=conversation, bible=bible, sections=names)


def parse(reply: str) -> list[Proposal] | None:
    """The suggested entries, or None when the reply is not the JSON asked for."""
    text = reply.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        entry = " ".join(str(item.get("entry") or "").split())
        if not entry:
            continue
        section = " ".join(str(item.get("section") or "").split()).strip("# ") or "Notes"
        out.append(Proposal(section, entry, " ".join(str(item.get("note") or "").split())))
    return out


def merge(text: str, accepted: list[Proposal]) -> str:
    """The bible with each entry added as a bullet at the end of its section
    (matched ignoring case), and new sections added at the end."""
    lines = text.rstrip("\n").splitlines()
    by_section: dict[str, list[str]] = {}
    order: list[str] = []
    for p in accepted:
        key = p.section.lower()
        if key not in by_section:
            by_section[key] = []
            order.append(p.section)
        by_section[key].append(f"- {p.entry}")

    # Where each existing section ends: the line before the next heading of level 1 or 2.
    starts: list[tuple[int, str]] = []
    fence = None
    for i, line in enumerate(lines):
        m = _FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        h = _HEADING.match(line)
        if h:
            starts.append((i, h.group(1).strip().lower()))
        elif re.match(r"^#\s", line) and starts:
            starts.append((i, ""))  # a level-1 heading ends the section before it
    inserts: dict[int, list[str]] = {}
    for n, (i, name) in enumerate(starts):
        if name not in by_section or not name:
            continue
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        last = end - 1
        while last > i and not lines[last].strip():
            last -= 1
        inserts.setdefault(last, [])
        if last == i:  # an empty section: leave a blank line under the heading
            inserts[last].append("")
        inserts[last].extend(by_section.pop(name))
    out: list[str] = []
    for i, line in enumerate(lines):
        out.append(line)
        out.extend(inserts.get(i, []))
    for section in order:
        entries = by_section.get(section.lower())
        if entries:
            out += ["", f"## {section}", ""] + entries
    return "\n".join(out) + "\n"
