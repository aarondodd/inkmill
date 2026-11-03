"""Thin wrapper over the git command line, safe to call from a TUI.

Git must never stop to ask a question: the terminal belongs to Inkmill, so a
prompt would hang the screen. Every call runs with prompts disabled
(``GIT_TERMINAL_PROMPT=0``, and ssh in batch mode unless the user configured
their own ssh command), no stdin and a timeout. Failures come back as text,
which :func:`advice` turns into something a writer can act on.

Graphical credential helpers, such as Git Credential Manager on Windows,
still work: they open their own window rather than reading the terminal.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

LOCAL_TIMEOUT = 20
NETWORK_TIMEOUT = 120


class GitMissing(Exception):
    pass


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def text(self) -> str:
        return (self.err.strip() + "\n" + self.out.strip()).strip()


def git_path() -> str | None:
    return shutil.which("git")


def install_hint() -> str:
    if sys.platform == "win32":
        return "Install Git for Windows (winget install Git.Git, or https://git-scm.com) and restart Inkmill."
    if "com.termux" in os.environ.get("PREFIX", "") or os.environ.get("TERMUX_VERSION"):
        return "Install it with: pkg install git (and pkg install openssh for SSH remotes)."
    if sys.platform == "darwin":
        return "Install it with: xcode-select --install, or brew install git."
    return "Install it with your package manager, for example: sudo apt install git."


_ssh_configured: dict[str, bool] = {}


def _env(cwd: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    # English messages, so advice() can recognize them.
    env["LC_ALL"] = "C"
    env["LANGUAGE"] = "C"
    if "GIT_SSH_COMMAND" not in env and "GIT_SSH" not in env:
        key = str(cwd)
        if key not in _ssh_configured:
            try:
                probe = subprocess.run(
                    ["git", "config", "--get", "core.sshCommand"],
                    cwd=cwd, capture_output=True, text=True, timeout=LOCAL_TIMEOUT, stdin=subprocess.DEVNULL,
                )
                _ssh_configured[key] = bool(probe.stdout.strip())
            except (OSError, subprocess.TimeoutExpired):
                _ssh_configured[key] = False
        if not _ssh_configured[key]:
            env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=20"
    return env


def run(args: list[str], cwd: Path, *, timeout: int = LOCAL_TIMEOUT) -> Result:
    exe = git_path()
    if exe is None:
        raise GitMissing(install_hint())
    try:
        proc = subprocess.run(
            [exe, "-c", "core.quotepath=false", *args],
            cwd=cwd,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            env=_env(cwd),
        )
    except subprocess.TimeoutExpired:
        return Result(-1, "", f"git {args[0]} timed out after {timeout} seconds")
    except OSError as exc:
        return Result(-1, "", f"could not run git: {exc}")
    return Result(proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace"))


def repo_root(path: Path) -> Path | None:
    folder = path if path.is_dir() else path.parent
    if not folder.is_dir():
        return None
    result = run(["rev-parse", "--show-toplevel"], folder)
    if not result.ok:
        return None
    return Path(result.out.strip())


@dataclass
class Status:
    branch: str = ""
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    changes: list[tuple[str, str]] = field(default_factory=list)  # (code, path relative to root)
    error: str | None = None

    def changed(self, rel: str) -> bool:
        return any(path == rel for _, path in self.changes)


def status(root: Path) -> Status:
    result = run(["status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all"], root)
    st = Status()
    if not result.ok:
        st.error = result.text
        return st
    fields = result.out.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if not entry:
            continue
        if entry.startswith("# branch.head "):
            st.branch = entry.split(" ", 2)[2]
        elif entry.startswith("# branch.upstream "):
            st.upstream = entry.split(" ", 2)[2]
        elif entry.startswith("# branch.ab "):
            parts = entry.split()
            st.ahead, st.behind = int(parts[2].lstrip("+")), abs(int(parts[3]))
        elif entry[0] == "1":
            parts = entry.split(" ", 8)
            st.changes.append((parts[1], parts[8]))
        elif entry[0] == "2":
            parts = entry.split(" ", 9)
            st.changes.append((parts[1], parts[9]))
            i += 1  # the original path follows
        elif entry[0] == "u":
            parts = entry.split(" ", 10)
            st.changes.append(("UU", parts[10]))
        elif entry[0] == "?":
            st.changes.append(("??", entry[2:]))
    return st


def relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def commit(root: Path, message: str, paths: list[Path] | None = None) -> Result:
    if paths:
        rels = [relative(root, p) for p in paths]
        added = run(["add", "--", *rels], root)
        if not added.ok:
            return added
        return run(["commit", "-m", message, "--", *rels], root)
    added = run(["add", "-A"], root)
    if not added.ok:
        return added
    return run(["commit", "-m", message], root)


def head(root: Path) -> str:
    result = run(["rev-parse", "HEAD"], root)
    return result.out.strip() if result.ok else ""


def count_between(root: Path, old: str, new: str) -> int:
    if not old or not new or old == new:
        return 0
    result = run(["rev-list", "--count", f"{old}..{new}"], root)
    try:
        return int(result.out.strip())
    except ValueError:
        return 0


def pull(root: Path, mode: str = "ff-only") -> Result:
    flag = {"ff-only": "--ff-only", "rebase": "--rebase", "merge": "--no-rebase"}.get(mode, "--ff-only")
    return run(["pull", flag, "--autostash"], root, timeout=NETWORK_TIMEOUT)


def abort_rebase(root: Path) -> None:
    run(["rebase", "--abort"], root)


def abort_merge(root: Path) -> None:
    run(["merge", "--abort"], root)


def remotes(root: Path) -> list[str]:
    result = run(["remote"], root)
    return [r for r in result.out.split() if r] if result.ok else []


def push(root: Path, *, set_upstream: str | None = None) -> Result:
    args = ["push"]
    if set_upstream:
        args += ["-u", set_upstream, "HEAD"]
    return run(args, root, timeout=NETWORK_TIMEOUT)


def log(root: Path, path: Path, limit: int = 50) -> Result:
    return run(
        ["log", "--follow", f"-n{limit}", "--date=short", "--format=%h  %ad  %an  %s", "--", relative(root, path)],
        root,
    )


def init(folder: Path) -> Result:
    return run(["init"], folder)


def set_identity(root: Path, name: str, email: str, *, global_: bool = False) -> Result:
    scope = ["--global"] if global_ else []
    first = run(["config", *scope, "user.name", name], root)
    if not first.ok:
        return first
    return run(["config", *scope, "user.email", email], root)


def get_identity(root: Path) -> tuple[str, str]:
    name = run(["config", "user.name"], root).out.strip()
    email = run(["config", "user.email"], root).out.strip()
    return name, email


# -- turning failures into advice ---------------------------------------------

KIND_PATTERNS = [
    ("identity", r"Please tell me who you are|empty ident name|unable to auto-detect email"),
    ("diverged", r"Not possible to fast-forward|diverging branches|Need to specify how to reconcile|fatal: Not possible"),
    ("conflict", r"CONFLICT|could not apply|Resolve all conflicts|Automatic merge failed"),
    ("nothing", r"nothing to commit|no changes added to commit|nothing added to commit"),
    ("no-upstream", r"has no upstream branch|There is no tracking information|no upstream configured"),
    ("rejected", r"\[rejected\]|failed to push some refs|fetch first|non-fast-forward"),
    ("auth", r"could not read Username|could not read Password|terminal prompts disabled|Authentication failed|"
             r"Invalid username or password|HTTP Basic: Access denied|returned error: 40[13]"),
    ("publickey", r"Permission denied \(publickey|sign_and_send_pubkey|Load key .*: (bad permissions|invalid format)"),
    ("hostkey", r"Host key verification failed|REMOTE HOST IDENTIFICATION HAS CHANGED"),
    ("network", r"Could not resolve host|Network is unreachable|Connection timed out|Connection refused|"
                r"timed out after|Operation timed out|unable to access .*: Failed to connect"),
    ("ownership", r"dubious ownership"),
    ("local-changes", r"Your local changes to the following files would be overwritten|Please commit your changes or stash them"),
    ("not-repo", r"not a git repository"),
]

ADVICE = {
    "auth": (
        "Git needs a username and password (or token) and cannot ask for one inside Inkmill. "
        "Set up a credential helper once from a terminal, then try again: Git Credential Manager "
        "(included with Git for Windows), 'gh auth login' for GitHub, or switch the remote to an SSH URL."
    ),
    "publickey": (
        "The SSH key was refused or could not be used without a prompt. Add your key to an agent "
        "('ssh-add', after starting ssh-agent) and check the public key is on your account. "
        "Inkmill runs ssh in batch mode, so a key with a passphrase must already be in the agent."
    ),
    "hostkey": "The server's host key is unknown or changed. Connect once from a terminal (for example 'ssh -T git@github.com') to check and accept it.",
    "network": "The remote could not be reached. Check the network connection and try again.",
    "no-upstream": "This branch does not track a remote branch yet.",
    "rejected": "The remote has commits you do not have yet. Pull first, then push again.",
    "ownership": (
        "Git refuses to work in this folder because another user owns it (common on Android shared storage). "
        "From a terminal run: git config --global --add safe.directory '*' (or name this folder instead of '*')."
    ),
    "local-changes": "Uncommitted changes in other files would be overwritten. Commit them first (Git > Commit Everything), then pull.",
    "conflict": "The changes conflict with your own. Inkmill stopped and put everything back as it was; resolve it from a terminal with git, then pull again.",
    "not-repo": "This document is not inside a git repository.",
}


def kind(text: str) -> str | None:
    for name, pattern in KIND_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return None


def advice(text: str) -> str:
    found = kind(text)
    if found and found in ADVICE:
        return ADVICE[found]
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "git failed without saying why."
