"""Suggested edits and continuations: reading the suggestions back, finding
them in the text, and writing them in as tracked changes or applying them.
No UI code.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass

from .conversation import SUGGEST

# CriticMarkup delimiters; text holding one cannot be marked up safely.
CRITIC = ("{++", "++}", "{--", "--}", "{~~", "~~}", "~>", "{==", "==}", "{>>", "<<}")
_WORDS = re.compile(r"(\s+)")
ATTACHES = tuple(",.;:!?)]}'’")


@dataclass
class Edit:
    find: str
    replace: str
    why: str = ""

    def label(self) -> str:
        if not self.find:
            return f"add {self.replace!r}"
        if not self.replace:
            return f"delete {self.find!r}"
        return f"{self.find!r} -> {self.replace!r}"


@dataclass
class Placed:
    start: int
    end: int
    edit: Edit


def request(how: str) -> str:
    how = " ".join(how.split()).rstrip(".") or "fix spelling, grammar and clumsy phrasing"
    return SUGGEST.format(how=how)


def parse(reply: str) -> list[Edit] | None:
    """The suggested edits, or None when the reply is not the JSON asked for."""
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
        find = item.get("find")
        if not isinstance(find, str) or not find or find == item.get("replace"):
            continue
        replace = item.get("replace")
        out.append(Edit(find, replace if isinstance(replace, str) else "", " ".join(str(item.get("why") or "").split())))
    return out


def locate(text: str, edits: list[Edit]) -> tuple[list[Placed], list[Edit]]:
    """Where each edit applies in ``text``, in document order, and the edits
    that could not be placed: text not found, overlapping another edit, or
    touching CriticMarkup.

    Each edit is looked for after the previous one first (suggestions come in
    document order, so a repeated phrase lands on the right occurrence), then
    from the start.
    """
    placed: list[Placed] = []
    missed: list[Edit] = []
    after = 0
    for edit in edits:
        if any(token in edit.find or token in edit.replace or token in edit.why for token in CRITIC):
            missed.append(edit)
            continue
        at = text.find(edit.find, after)
        if at < 0:
            at = text.find(edit.find)
        if at < 0:
            missed.append(edit)
            continue
        end = at + len(edit.find)
        if any(at < p.end and p.start < end for p in placed) or _in_markup(text, at, end):
            missed.append(edit)
            continue
        placed.extend(narrow(Placed(at, end, edit)))
        after = end
    placed.sort(key=lambda p: p.start)
    return placed, missed


def narrow(placed: Placed) -> list[Placed]:
    """The edit cut down to the words that change, one piece per change.
    Claude quotes some context so the text is found, and may fold two fixes
    into one edit; the review should show each change on its own ("Their was
    a storm comming" -> "There was a storm coming" is two changes). The
    reason goes with the first piece."""
    edit = placed.edit
    old, new = _WORDS.split(edit.find), _WORDS.split(edit.replace)
    offsets = [0]
    for token in old:
        offsets.append(offsets[-1] + len(token))
    pieces = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        start = placed.start + offsets[i1]
        pieces.append(Placed(start, placed.start + offsets[i2], Edit("".join(old[i1:i2]), "".join(new[j1:j2]))))
    if not pieces:
        return []
    pieces[0].edit.why = edit.why
    return pieces


def _in_markup(text: str, start: int, end: int) -> bool:
    """Whether the span overlaps existing CriticMarkup."""
    from_mark = re.compile(
        r"\{\+\+.*?\+\+\}|\{--.*?--\}|\{~~.*?~~\}|\{==.*?==\}|\{>>.*?<<\}", re.DOTALL)
    return any(m.start() < end and start < m.end() for m in from_mark.finditer(text))


def _rewrite(text: str, placed: list[Placed], render) -> str:
    out, last = [], 0
    for p in placed:
        out.append(text[last:p.start])
        out.append(render(p.edit))
        last = p.end
    out.append(text[last:])
    return "".join(out)


def marked(text: str, placed: list[Placed]) -> str:
    """``text`` with each edit written in as a CriticMarkup suggestion, its
    reason as a comment after it."""

    def render(edit: Edit) -> str:
        if not edit.find:
            mark = f"{{++{edit.replace}++}}"
        elif edit.replace:
            mark = f"{{~~{edit.find}~>{edit.replace}~~}}"
        else:
            mark = f"{{--{edit.find}--}}"
        return mark + (f"{{>>{edit.why}<<}}" if edit.why else "")

    return _rewrite(text, placed, render)


def applied(text: str, placed: list[Placed]) -> str:
    return _rewrite(text, placed, lambda edit: edit.replace)


def to_markdown(edits: list[Edit]) -> str:
    """The suggestions as a readable list, for the conversation history."""
    if not edits:
        return "No edits suggested."
    lines = []
    for edit in edits:
        line = f"- {edit.label()}"
        if edit.why:
            line += f" ({edit.why})"
        lines.append(line)
    return "\n".join(lines)


def join(before: str, reply: str, after: str = "") -> str:
    """The continuation as it should be inserted between ``before`` and
    ``after``: a space or paragraph break added where the text needs one."""
    body = reply.strip()
    if not body:
        return ""
    lead = reply[:len(reply) - len(reply.lstrip())]
    if not before.strip() or before.endswith("\n\n"):
        sep = ""
    elif "\n\n" in lead:
        sep = "\n" if before.endswith("\n") else "\n\n"
    elif before.endswith(("\n", " ", "\t")) or body.startswith(ATTACHES):
        sep = ""
    else:
        sep = " "
    tail = ""
    if after and not after[0].isspace():
        tail = "\n\n" if "\n" in sep or before.endswith("\n") else " "
    return sep + body + tail
