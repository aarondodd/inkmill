"""The wording of the AI commands, and turning a saved Claude Code
conversation back into readable Markdown. No UI code.

Claude Code keeps each conversation as a JSON Lines file under its config
folder (``~/.claude``, or ``CLAUDE_CONFIG_DIR``), in
``projects/<folder>/<session id>.jsonl``. Each line is one record: the
writer's request, a piece of Claude's reply (text, thinking or a tool call),
a tool's result, or bookkeeping. Only the requests and the reply text are
kept here, and each request loses the note naming the project's files that
Inkmill puts at the top of it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# The fixed wording of the commands, so a saved conversation can name them.
FEEDBACK = (
    "Give me feedback on this passage as an experienced editor would: what works, what does not, and the "
    "three changes that would help most. Consider clarity, pacing, voice, dialogue and structure, and quote "
    "the lines you mean."
)
SUMMARY = "Summarize this in a short paragraph, then list its key points."
REWRITE = (
    "Rewrite the passage below three different ways, {how}. Keep the meaning and the writer's voice. "
    "Reply with only the three versions, separated by lines containing just ---, without numbers or "
    "commentary."
)
CONTINUITY = (
    "List every continuity problem you find: characters' names, ages, looks and relationships; dates and the "
    "order of events; places and distances; objects; and facts that contradict the research notes or the "
    "story bible. For each, quote both passages and name the chapters. Group them by kind, most serious "
    "first. If you find none in a group, leave it out."
)
WHOLE_DOCUMENT = "The text is the whole document the writer is working on (named above); read it."
PASSAGE = "The passage:\n\n"
TEXT = "The text:\n\n"
BIBLE = "The writer's story bible:\n\n"
HEADER_START = "Project folder: "
WORKING_ON = "The writer is working on: "

_REWRITE = re.compile(r"Rewrite the passage below three different ways, (.+?)\. Keep the meaning")
_HEADING = re.compile(r"^(#{1,4})(\s)", re.MULTILINE)
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


@dataclass
class Turn:
    role: str  # "me" or "claude"
    text: str
    label: str = ""  # the command a request came from, when known
    looked_at: list[str] = field(default_factory=list)
    about: str = ""  # the document a request was made from, when known


@dataclass
class Exchange:
    """One request and the reply to it, as the reply panel shows them."""

    label: str
    request: str
    reply: str = ""
    about: str = ""
    looked_at: list[str] = field(default_factory=list)


def claude_home() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def find(session_id: str, home: Path | None = None) -> Path | None:
    """The file Claude Code keeps conversation ``session_id`` in, or None."""
    if not re.fullmatch(r"[\w-]+", session_id or ""):
        return None
    hits = sorted((home or claude_home()).glob(f"projects/*/{session_id}.jsonl"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def _looked_at(block: dict) -> str:
    data = block.get("input") or {}
    name = block.get("name", "")
    if name == "Read" and data.get("file_path"):
        return Path(str(data["file_path"])).name
    target = data.get("pattern") or data.get("path") or data.get("command") or ""
    return f"{name} {target}".strip()


def turns(path: Path) -> list[Turn]:
    """The requests and replies in a Claude Code conversation file, in order.

    A reply that reads files before answering keeps only the text after the
    last file it read, as the reply panel does, plus the names of the files.
    """
    out: list[Turn] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") not in ("user", "assistant"):
            continue
        if record.get("isMeta") or record.get("isSidechain") or record.get("isCompactSummary"):
            continue
        content = (record.get("message") or {}).get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        if not isinstance(blocks, list):
            continue
        if record["type"] == "user":
            text = "\n\n".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
            if text.strip():  # tool results come back as user records with no text
                out.append(Turn("me", text.strip()))
            continue
        if not out or out[-1].role != "claude":
            out.append(Turn("claude", ""))
        reply = out[-1]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                reply.looked_at.append(_looked_at(block))
                reply.text = ""
            elif block.get("type") == "text" and block.get("text", "").strip():
                piece = block["text"].strip()
                reply.text = f"{reply.text}\n\n{piece}" if reply.text else piece
    out = [t for t in out if t.text or t.looked_at]
    for turn in out:
        if turn.role == "me":
            turn.about = request_file(turn.text)
            turn.label, turn.text = clean_request(turn.text)
    return out


_cache: dict[Path, tuple[float, int, list[Turn]]] = {}


def load(path: Path) -> list[Turn]:
    """``turns(path)``, read again only when the file has changed."""
    stat = path.stat()
    hit = _cache.get(path)
    if hit and hit[0] == stat.st_mtime and hit[1] == stat.st_size:
        return hit[2]
    result = turns(path)
    _cache[path] = (stat.st_mtime, stat.st_size, result)
    return result


def request_file(text: str) -> str:
    """The name of the document a request was made from, from the note at its top."""
    if not text.startswith(HEADER_START):
        return ""
    for line in text.partition("\n\n")[0].splitlines():
        if line.startswith(WORKING_ON):
            value = line[len(WORKING_ON):].strip()
            copy = re.search(r"\(a copy of (.+?) with the writer's unsaved changes\)$", value)
            value = copy.group(1) if copy else value
            return "" if value == "not saved yet" else Path(value.replace("\\", "/")).name
    return ""


def exchanges(conversation: list[Turn]) -> list[Exchange]:
    """Each request paired with the reply after it."""
    out: list[Exchange] = []
    for turn in conversation:
        if turn.role == "me":
            out.append(Exchange(turn.label, turn.text, about=turn.about))
        elif out and not out[-1].reply and not out[-1].looked_at:
            out[-1].reply, out[-1].looked_at = turn.text, list(turn.looked_at)
        else:
            out.append(Exchange("", "", turn.text, looked_at=list(turn.looked_at)))
    return out


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.replace("**", "").replace("__", "").replace("`", "")
        line = re.sub(r"^\s*(?:#+\s*|>\s*|[-*+]\s+|\d+[.)]\s+)", "", line).replace("*", "").strip()
        if line and line != "(About the whole document.)" and line != "About this passage:":
            return line
    return ""


def describe(exchange: Exchange, width: int = 60) -> str:
    """A one-line description for the list of turns: the question for a
    question, otherwise the start of the reply."""
    if exchange.label in ("", "Ask", "Follow-up"):
        line = _first_line(exchange.request) or _first_line(exchange.reply)
    else:
        line = _first_line(exchange.reply) or _first_line(exchange.request)
    return line if len(line) <= width else line[: width - 3].rstrip() + "..."


def clean_request(text: str, from_inkmill: bool = False) -> tuple[str, str]:
    """(command name, what the writer asked about) for one request as Inkmill
    sent it. Requests typed in Claude Code itself come back unchanged, unnamed,
    unless ``from_inkmill`` says the request is known to be Inkmill's."""
    if not text.startswith(HEADER_START):
        if text.startswith(BIBLE) or text.startswith("# Manuscript: "):
            return _name_command(text, context_first=True)
        return _name_command(text, context_first=False) if from_inkmill else ("", text)
    head, _, rest = text.partition("\n\n")
    return _name_command(rest if head else text, context_first=False)


def _name_command(text: str, *, context_first: bool) -> tuple[str, str]:
    for wording, label in ((FEEDBACK, "Feedback"), (SUMMARY, "Summarize"), (CONTINUITY, "Continuity Check")):
        at = text.find(wording)
        if at >= 0 and (context_first or at == 0 or label == "Continuity Check"):
            return label, "" if label == "Continuity Check" else _about(text[at + len(wording):])
    match = _REWRITE.search(text)
    if match:
        end = text.find("commentary.", match.end())
        passage = text[end + len("commentary."):] if end >= 0 else ""
        return f"Rewrite ({match.group(1)})", _quote(passage.strip())
    if context_first:
        return "Ask", text  # the question cannot be told apart from the story bible before it
    return "Ask", _about(text)


def _about(text: str) -> str:
    """The rest of a request, with the document text it carried shortened."""
    text = text.strip()
    for marker, render in ((WHOLE_DOCUMENT, None), (PASSAGE, "passage"), (TEXT, None)):
        at = text.find(marker)
        if at < 0:
            continue
        before = text[:at].strip()
        about = "(About the whole document.)" if render is None else "About this passage:\n\n" + _quote(text[at + len(marker):].strip())
        return f"{before}\n\n{about}".strip()
    return text


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.splitlines())


def _demote(text: str) -> str:
    """Claude's own headings, two levels down, so they sit under the turn's heading."""
    out, fence = [], None
    for line in text.splitlines():
        m = _FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
        elif m:
            fence = m.group(1)
        else:
            line = _HEADING.sub(lambda h: "#" * min(len(h.group(1)) + 2, 6) + h.group(2), line)
        out.append(line)
    return "\n".join(out)


def to_markdown(conversation: list[Turn], title: str, intro: str = "") -> str:
    """A research note body: the conversation as headed turns."""
    parts = [f"# {title}"]
    if intro:
        parts.append(intro)
    for turn in conversation:
        if turn.role == "me":
            parts.append(f"## Me: {turn.label}" if turn.label else "## Me")
            if turn.text:
                parts.append(turn.text)
        else:
            parts.append("## Claude")
            if turn.looked_at:
                parts.append("_Looked at: " + ", ".join(turn.looked_at) + "_")
            if turn.text:
                parts.append(_demote(turn.text))
    return "\n\n".join(parts) + "\n"
