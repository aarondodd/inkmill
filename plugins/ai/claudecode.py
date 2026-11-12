"""Run the Claude Code command line program (`claude`) in headless mode. No UI code.

Requests go through the writer's own installed and logged-in copy of Claude
Code, so they count against their Claude plan rather than API billing.
Inkmill never reads or stores the login; it only starts the program.

Each request is one `claude -p` run. A conversation continues across runs
with `--resume <session id>`; Claude Code keeps the history on disk, filed
under the folder it was started in, so every run for a project starts in the
same folder. The run loads none of the writer's Claude Code settings, hooks,
plugins, MCP servers or CLAUDE.md files, and gets either no tools or only the
read-only file tools (Read, Grep, Glob), which Claude Code confines to the
project folder and any folders named with --add-dir.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

READ_TOOLS = "Read,Grep,Glob"


class ClaudeCodeError(Exception):
    pass


class SessionMissing(ClaudeCodeError):
    """Claude Code has no conversation with the id we asked to resume."""


@dataclass
class Reply:
    text: str
    session_id: str
    tools: list[dict] = field(default_factory=list)  # the tool calls Claude made, in order


def split_command(command: str) -> list[str]:
    """The program and any leading arguments, from a setting such as
    ``claude`` or ``~/bin/claude-wrapper --flag``."""
    command = (command or "claude").strip()
    if Path(command).expanduser().is_file():
        return [str(Path(command).expanduser())]
    if sys.platform == "win32":
        # Windows paths keep their backslashes; drop the quotes around each part.
        return [part.strip('"') for part in shlex.split(command, posix=False)] or ["claude"]
    return shlex.split(command) or ["claude"]


def find(command: str = "") -> list[str] | None:
    """The command line that starts claude, with its program resolved to a full path, or None."""
    parts = split_command(command)
    exe = shutil.which(str(Path(parts[0]).expanduser()))
    return [exe, *parts[1:]] if exe else None


def new_session_id() -> str:
    return str(uuid.uuid4())


def build_args(
    exe: list[str],
    *,
    system: str,
    model: str = "",
    effort: str = "",
    session: str | None = None,
    resume: bool = False,
    files: bool = True,
    add_dirs: tuple[Path, ...] = (),
) -> list[str]:
    """The command line for one request. ``session`` None means a one-off run that is not saved."""
    args = [
        *exe, "-p",
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--strict-mcp-config", "--setting-sources", "",
        "--system-prompt", system,
    ]
    if files:
        args += ["--tools", READ_TOOLS, "--allowedTools", READ_TOOLS]
        for folder in add_dirs:
            args += ["--add-dir", str(folder)]
    else:
        args += ["--tools", ""]
    if model:
        args += ["--model", model]
    if effort:
        args += ["--effort", effort]
    if session is None:
        args.append("--no-session-persistence")
    elif resume:
        args += ["--resume", session]
    else:
        args += ["--session-id", session]
    return args


def describe_tool(block: dict) -> str:
    """A short line for the reply panel while Claude reads files."""
    name = block.get("name", "a tool")
    data = block.get("input") or {}
    target = data.get("file_path") or data.get("pattern") or data.get("path") or ""
    if target:
        target = Path(str(target)).name if name == "Read" else str(target)
    verb = {"Read": "Reading", "Grep": "Searching for", "Glob": "Looking for"}.get(name, f"Using {name}:")
    return f"{verb} {target}".strip() + "..."


def run(
    args: list[str],
    cwd: Path,
    prompt: str,
    on_text: Callable[[str], None],
    *,
    on_tool: Callable[[str], None] | None = None,
    on_reset: Callable[[], None] | None = None,
    cancel: threading.Event | None = None,
) -> Reply:
    """Start claude, send ``prompt`` on stdin and stream the reply.

    ``on_text`` gets each piece of reply text. When Claude stops to read a
    file and then writes again, ``on_reset`` is called first, so the panel
    shows the answer rather than the "I'll read the chapter" preamble.
    Returns the final reply and the session id.
    """
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.Popen(
            args, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", creationflags=flags,
        )
    except OSError as exc:
        raise ClaudeCodeError(f"cannot run {args[0]}: {exc.strerror or exc}") from exc

    errors: list[str] = []

    def drain_stderr() -> None:
        assert proc.stderr is not None
        errors.extend(proc.stderr.read().splitlines())

    def watch_cancel() -> None:
        while proc.poll() is None:
            if cancel is not None and cancel.wait(0.2):
                proc.terminate()
                return

    threading.Thread(target=drain_stderr, daemon=True).start()
    if cancel is not None:
        threading.Thread(target=watch_cancel, daemon=True).start()
    try:
        assert proc.stdin is not None
        proc.stdin.write(prompt)
        proc.stdin.close()
    except OSError:
        pass  # claude exited early; its output says why

    final: dict | None = None
    stray: list[str] = []
    pieces: list[str] = []
    tools: list[dict] = []
    used_tool = False
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            stray.append(line)
            continue
        kind = data.get("type")
        if kind == "stream_event":
            event = data.get("event") or {}
            if event.get("type") == "message_start" and used_tool:
                used_tool = False
                pieces.clear()
                if on_reset:
                    on_reset()
            elif event.get("type") == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    pieces.append(delta["text"])
                    on_text(delta["text"])
        elif kind == "assistant":
            for block in (data.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    used_tool = True
                    tools.append(block)
                    if on_tool:
                        on_tool(describe_tool(block))
        elif kind == "result":
            final = data
    code = proc.wait()
    if cancel is not None and cancel.is_set():
        return Reply("".join(pieces), (final or {}).get("session_id", ""), tools)
    if final is None:
        message = " ".join(stray + errors).strip() or f"claude stopped with exit code {code}"
        raise ClaudeCodeError(friendly(message))
    if final.get("is_error"):
        message = str(final.get("result") or "; ".join(final.get("errors") or []) or "Claude Code reported an error")
        if "No conversation found" in message:
            raise SessionMissing(message)
        raise ClaudeCodeError(friendly(message))
    text = final.get("result")
    return Reply(str(text) if text is not None else "".join(pieces), str(final.get("session_id", "")), tools)


def friendly(message: str) -> str:
    lowered = message.lower()
    if "not logged in" in lowered or "/login" in lowered or "authentication" in lowered:
        return ("Claude Code is not logged in. Run claude in a terminal, log in with /login, "
                "then try again. (" + message + ")")
    if "usage limit" in lowered or "rate limit" in lowered:
        return "Your Claude plan's usage limit was reached; try again later. (" + message + ")"
    return message


class Sessions:
    """Which Claude Code conversation belongs to which project folder."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def key(folder: Path) -> str:
        return folder.resolve().as_posix()

    def get(self, folder: Path) -> str | None:
        entry = self._load().get(self.key(folder))
        return entry.get("id") if isinstance(entry, dict) else None

    def set(self, folder: Path, session_id: str) -> None:
        data = self._load()
        entry = data.get(self.key(folder))
        turns = entry.get("turns", 0) + 1 if isinstance(entry, dict) and entry.get("id") == session_id else 1
        data[self.key(folder)] = {"id": session_id, "turns": turns}
        self._save(data)

    def turns(self, folder: Path) -> int:
        entry = self._load().get(self.key(folder))
        return int(entry.get("turns", 0)) if isinstance(entry, dict) else 0

    def forget(self, folder: Path) -> None:
        data = self._load()
        if data.pop(self.key(folder), None) is not None:
            self._save(data)
