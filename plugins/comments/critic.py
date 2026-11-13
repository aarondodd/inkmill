"""CriticMarkup: comments and suggested edits in plain text. No UI code.

    {++added++}  {--deleted--}  {~~old~>new~~}  {==highlighted==}  {>>comment<<}

A highlight or a suggested edit followed directly by a comment is one
annotation: the comment is about the highlighted text, or gives the reason
for the edit, and goes with it when the edit is accepted or rejected.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

MARK = re.compile(
    r"\{\+\+(?P<add>.*?)\+\+\}(?:\{>>(?P<add_note>.*?)<<\})?"
    r"|\{--(?P<delete>.*?)--\}(?:\{>>(?P<delete_note>.*?)<<\})?"
    r"|\{~~(?P<old>.*?)~>(?P<new>.*?)~~\}(?:\{>>(?P<replace_note>.*?)<<\})?"
    r"|\{==(?P<mark>.*?)==\}(?:\{>>(?P<note>.*?)<<\})?"
    r"|\{>>(?P<comment>.*?)<<\}",
    re.DOTALL,
)


@dataclass
class Mark:
    start: int
    end: int
    kind: str  # "add", "delete", "replace", "highlight", "comment"
    text: str  # the text involved (added, deleted, old>new, highlighted)
    note: str = ""

    def accepted(self) -> str:
        if self.kind == "replace":
            return self.text.split("\0")[1]
        return {"add": self.text, "delete": "", "highlight": self.text, "comment": ""}[self.kind]

    def rejected(self) -> str:
        if self.kind == "replace":
            return self.text.split("\0")[0]
        return {"add": "", "delete": self.text, "highlight": self.text, "comment": ""}[self.kind]

    def label(self) -> str:
        if self.kind == "highlight":
            return f"{self.text!r}: {self.note}" if self.note else f"highlight {self.text!r}"
        if self.kind == "replace":
            old, new = self.text.split("\0")
            shown = f"change {old!r} to {new!r}"
        else:
            shown = {"add": "add", "delete": "delete", "comment": "comment"}[self.kind] + f" {self.text!r}"
        return f"{shown} ({self.note})" if self.note else shown


def marks(text: str) -> list[Mark]:
    found = []
    for m in MARK.finditer(text):
        if m.group("add") is not None:
            found.append(Mark(m.start(), m.end(), "add", m.group("add"), m.group("add_note") or ""))
        elif m.group("delete") is not None:
            found.append(Mark(m.start(), m.end(), "delete", m.group("delete"), m.group("delete_note") or ""))
        elif m.group("old") is not None:
            found.append(Mark(m.start(), m.end(), "replace", m.group("old") + "\0" + m.group("new"),
                              m.group("replace_note") or ""))
        elif m.group("mark") is not None:
            found.append(Mark(m.start(), m.end(), "highlight", m.group("mark"), m.group("note") or ""))
        else:
            found.append(Mark(m.start(), m.end(), "comment", m.group("comment")))
    return found


def resolve(text: str, *, accept: bool, kinds: set[str] | None = None) -> str:
    """Accept or reject every mark (of ``kinds``), returning clean text."""
    out, last = [], 0
    for mark in marks(text):
        if kinds is not None and mark.kind not in kinds:
            continue
        out.append(text[last:mark.start])
        out.append(mark.accepted() if accept else mark.rejected())
        last = mark.end
    out.append(text[last:])
    return "".join(out)


def to_html(text: str) -> str:
    """Show the marks in exported HTML with ins, del, mark and comment spans."""

    def render(m: re.Match) -> str:
        esc = html.escape
        reason = m.group("add_note") or m.group("delete_note") or m.group("replace_note")
        after = f'<span class="critic-comment">{esc(reason)}</span>' if reason else ""
        if m.group("add") is not None:
            return f'<ins class="critic">{esc(m.group("add"))}</ins>{after}'
        if m.group("delete") is not None:
            return f'<del class="critic">{esc(m.group("delete"))}</del>{after}'
        if m.group("old") is not None:
            return (f'<del class="critic">{esc(m.group("old"))}</del>'
                    f'<ins class="critic">{esc(m.group("new"))}</ins>{after}')
        if m.group("mark") is not None:
            note = m.group("note")
            title = f' title="{esc(note, quote=True)}"' if note else ""
            span = f'<span class="critic-comment">{esc(note)}</span>' if note else ""
            return f'<mark class="critic"{title}>{esc(m.group("mark"))}</mark>{span}'
        return f'<span class="critic-comment">{esc(m.group("comment"))}</span>'

    return MARK.sub(render, text)


EXPORT_CSS = (
    "<style>.critic-comment{font-size:.85em;padding:0 .3em;margin:0 .2em;border-radius:3px;"
    "background:#fff3b0;color:#5a4800}ins.critic{background:#d9f7d9;text-decoration:underline}"
    "del.critic{background:#fbd8d8}</style>\n"
)
