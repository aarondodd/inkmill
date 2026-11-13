"""The wording of the AI commands, and turning a saved Claude Code
conversation back into readable Markdown. No UI code.

Claude Code keeps each conversation as a JSON Lines file under its config
folder (``~/.claude``, or ``CLAUDE_CONFIG_DIR``), in
``projects/<folder>/<session id>.jsonl``. Each line is one record: the
writer's request, a piece of Claude's reply (text, thinking or a tool call),
a tool's result, or bookkeeping. Only the requests and the reply text are
kept here, and each request loses the note naming the project's files that
Inkmill puts at the top of it.

``Log`` is Inkmill's own lasting copy of a project's conversation, kept in
the project folder at ``.inkmill/ai-conversation.jsonl``, one JSON object per
line. It outlives Claude Code's clean-up of old conversations, moves with the
folder, and also holds the turns of the providers that keep no history.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from dataclasses import asdict, dataclass, field
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
CONTINUE = (
    "Continue the writer's text from where the passage below stops, in their voice, keeping to the story "
    "bible and to what we have discussed. Reply with only the new text, with no heading, notes or "
    "commentary, starting exactly where the passage stops: begin with a blank line if a new paragraph "
    "comes next."
)
SUGGEST = (
    "Suggest edits to the text: {how}. Change only what that asks for and keep the writer's voice. "
    "Reply with only a JSON array and no other text. Each item is an object with \"find\" (the exact text "
    "to change, copied character for character from the document, long enough to occur only once, at "
    "most a few sentences), \"replace\" (what it becomes; empty to delete it) and \"why\" (a short "
    "reason). Make each item a single change. Reply [] if nothing needs changing."
)
ENDS_HERE = "The passage, which ends where the new text goes:\n\n"
FOLLOWS = "The text that comes after the new text (do not repeat it; lead into it):\n\n"
WHOLE_DOCUMENT = "The text is the whole document the writer is working on (named above); read it."
PASSAGE = "The passage:\n\n"
TEXT = "The text:\n\n"
BIBLE = "The writer's story bible:\n\n"
HEADER_START = "Project folder: "
WORKING_ON = "The writer is working on: "
# Put before the first request of a new Claude Code conversation when the
# project's log holds turns Claude Code no longer has.
SEED_START = "[Earlier conversation]\n"
SEED_END = "[End of the earlier conversation]"
LOG_FOLDER = ".inkmill"
LOG_NAME = "ai-conversation.jsonl"
EARLIER_NAME = "earlier-conversation.md"

_REWRITE = re.compile(r"Rewrite the passage below three different ways, (.+?)\. Keep the meaning")
_SUGGEST = re.compile(r"^Suggest edits to the text: (.+?)\. Change only what that asks for")
_HEADING = re.compile(r"^(#{1,4})(\s)", re.MULTILINE)
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


@dataclass
class Turn:
    role: str  # "me" or "claude"
    text: str
    label: str = ""  # the command a request came from, when known
    looked_at: list[str] = field(default_factory=list)
    about: str = ""  # the document a request was made from, when known
    time: str = ""  # when it was written, as stamp() makes it


@dataclass
class Exchange:
    """One request and the reply to it, as the reply panel shows them."""

    label: str
    request: str
    reply: str = ""
    about: str = ""
    looked_at: list[str] = field(default_factory=list)
    time: str = ""


def stamp(value: str | datetime.datetime | None = None) -> str:
    """A UTC time as ``2026-11-12T05:03:17Z``, from a datetime, an ISO string or now."""
    if isinstance(value, str):
        if not value:
            return ""
        try:
            value = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
    value = value or datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def looked_at(block: dict) -> str:
    """How a tool call reads in a saved turn: the file name, or the tool and its target."""
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
        when = stamp(str(record.get("timestamp") or ""))
        if record["type"] == "user":
            text = "\n\n".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
            if text.strip():  # tool results come back as user records with no text
                out.append(Turn("me", strip_seed(text.strip()), time=when))
            continue
        if not out or out[-1].role != "claude":
            out.append(Turn("claude", "", time=when))
        reply = out[-1]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                reply.looked_at.append(looked_at(block))
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
            out.append(Exchange(turn.label, turn.text, about=turn.about, time=turn.time))
        elif out and not out[-1].reply and not out[-1].looked_at:
            out[-1].reply, out[-1].looked_at = turn.text, list(turn.looked_at)
        else:
            out.append(Exchange("", "", turn.text, looked_at=list(turn.looked_at), time=turn.time))
    return out


def strip_seed(text: str) -> str:
    """A request without the earlier conversation Inkmill put in front of it."""
    if not text.startswith(SEED_START):
        return text
    end = text.find(SEED_END)
    return text[end + len(SEED_END):].lstrip() if end >= 0 else text


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
    for wording, label in ((FEEDBACK, "Feedback"), (SUMMARY, "Summarize"), (CONTINUITY, "Continuity Check"),
                           (CONTINUE, "Continue")):
        at = text.find(wording)
        if at >= 0 and (context_first or at == 0 or label == "Continuity Check"):
            return label, "" if label == "Continuity Check" else _about(text[at + len(wording):])
    match = _SUGGEST.search(text)
    if match:
        end = text.find("needs changing.", match.end())
        rest = text[end + len("needs changing."):] if end >= 0 else ""
        return f"Suggest Edits ({match.group(1)})", _about(rest)
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
    at = text.find(ENDS_HERE)
    if at >= 0:
        passage = text[at + len(ENDS_HERE):].split(FOLLOWS)[0].strip()
        if len(passage) > 300:
            passage = "..." + passage[-300:].lstrip()
        return f"{text[:at].strip()}\n\nContinuing after:\n\n{_quote(passage)}".strip()
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


def exchanges_to_turns(items: list[Exchange]) -> list[Turn]:
    out: list[Turn] = []
    for e in items:
        if e.label or e.request:
            out.append(Turn("me", e.request, e.label, about=e.about, time=e.time))
        out.append(Turn("claude", e.reply, looked_at=list(e.looked_at), time=e.time))
    return out


# -- reading a saved conversation note back ----------------------------------------

_TURN = re.compile(r"^## (Me(?::\s*(.*))?|Claude)\s*$")
_LOOKED = re.compile(r"^_Looked at: (.*)_$")
_DEMOTED = re.compile(r"^(#{3,6})(\s)")


def is_saved_conversation(text: str) -> bool:
    """Whether a document reads like one to_markdown() wrote."""
    lines = _body(text).splitlines()
    return any(_TURN.match(l) and l.startswith("## Me") for l in lines) and "## Claude" in lines


def _body(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            return text[end + 4:].lstrip("\n")
    return text


def _promote(text: str) -> str:
    out, fence = [], None
    for line in text.splitlines():
        m = _FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
        elif m:
            fence = m.group(1)
        else:
            line = _DEMOTED.sub(lambda h: "#" * (len(h.group(1)) - 2) + h.group(2), line)
        out.append(line)
    return "\n".join(out)


def from_markdown(text: str) -> list[Exchange]:
    """The exchanges in a note written by to_markdown()."""
    sections: list[tuple[str, str, list[str]]] = []  # (role, label, lines)
    fence = None
    for line in _body(text).splitlines():
        m = _FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
        elif m:
            fence = m.group(1)
        else:
            turn = _TURN.match(line)
            if turn:
                role = "claude" if turn.group(1) == "Claude" else "me"
                sections.append((role, (turn.group(2) or "").strip(), []))
                continue
        if sections:
            sections[-1][2].append(line)
    turns: list[Turn] = []
    for role, label, lines in sections:
        body = "\n".join(lines).strip()
        if role == "me":
            turns.append(Turn("me", body, label))
            continue
        found: list[str] = []
        first, _, rest = body.partition("\n")
        m = _LOOKED.match(first.strip())
        if m:
            found = [part.strip() for part in m.group(1).split(", ") if part.strip()]
            body = rest.strip()
        turns.append(Turn("claude", _promote(body), looked_at=found))
    return exchanges(turns)


# -- Inkmill's lasting log -----------------------------------------------------------

class Log:
    """A project's conversation as Inkmill keeps it, in the project folder.

    Each line is a turn (``"type": "turn"``) or a mark that the writer
    started a new conversation (``"type": "reset"``). A turn names the
    Claude Code session it belongs to, if any, so turns copied from Claude
    Code's own record are never copied twice.
    """

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.path = folder / LOG_FOLDER / LOG_NAME

    def records(self) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                out.append(record)
        return out

    def _write(self, records: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _exchange(record: dict) -> Exchange:
        return Exchange(
            str(record.get("label") or ""), str(record.get("request") or ""), str(record.get("reply") or ""),
            str(record.get("about") or ""), [str(x) for x in record.get("looked_at") or []], str(record.get("time") or ""),
        )

    def exchanges(self, *, since_reset: bool = False) -> list[Exchange]:
        """The turns, oldest first (by time; turns with no time come first)."""
        found: list[Exchange] = []
        for record in self.records():
            if record.get("type") == "reset":
                if since_reset:
                    found = []
            elif record.get("type", "turn") == "turn":
                found.append(self._exchange(record))
        return sorted(found, key=lambda e: e.time)

    def count(self, session: str) -> int:
        return sum(1 for r in self.records() if r.get("type", "turn") == "turn" and r.get("session") == session)

    def append(self, exchange: Exchange, *, session: str = "", provider: str = "", source: str = "inkmill") -> None:
        self.extend([exchange], session=session, provider=provider, source=source)

    def extend(self, items: list[Exchange], *, session: str = "", provider: str = "", source: str = "inkmill") -> None:
        records = []
        for e in items:
            record = {"type": "turn", **asdict(e), "time": e.time or stamp(), "session": session,
                      "provider": provider, "source": source}
            records.append(record)
        if records:
            self._write(records)

    def reset(self) -> None:
        self._write([{"type": "reset", "time": stamp()}])

    def sync(self, session: str, items: list[Exchange]) -> int:
        """Copy the turns of Claude Code session ``session`` that the log
        lacks (those past the ones it has). Returns how many were added."""
        new = items[self.count(session):]
        self.extend(new, session=session, provider="claude-code", source="claude-code")
        return len(new)

    def add_missing(self, items: list[Exchange], *, source: str) -> int:
        """Add the turns not already in the log (same command, request and reply)."""
        have = {(e.label, e.request, e.reply) for e in self.exchanges()}
        new = [e for e in items if (e.label, e.request, e.reply) not in have]
        self.extend(new, source=source)
        return len(new)


def transcripts_for(folder: Path, home: Path | None = None) -> list[Path]:
    """Claude Code's conversation files started in ``folder``, oldest first."""
    target = folder.resolve()
    found = []
    for path in (home or claude_home()).glob("projects/*/*.jsonl"):
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for _ in range(50):
                    line = fh.readline()
                    if not line:
                        break
                    try:
                        cwd = json.loads(line).get("cwd")
                    except (ValueError, AttributeError):
                        continue
                    if cwd:
                        if Path(cwd).resolve() == target:
                            found.append(path)
                        break
        except OSError:
            continue
    return sorted(found, key=lambda p: p.stat().st_mtime)
