"""Checking for a newer Inkmill and installing it.

The newest version is whatever ``src/inkmill/__init__.py`` says on the
repository's main branch, the same branch the plugin index is read from, and
the release notes come from ``CHANGELOG.md`` beside it.

How to install an update depends on how Inkmill was installed, which this
module works out from the running interpreter:

* pipx: ``pipx upgrade inkmill`` (it keeps packages added with ``pipx inject``),
* pip, in a virtual environment or the user's site-packages (Termux):
  ``python -m pip install --upgrade`` with the same source as before,
* a source checkout installed with ``pip install -e``: ``git pull``, done by
  hand.

Inkmill runs the command itself where it can. On Windows a running program's
files are locked, so the command runs in a new console window once Inkmill
has closed. Where neither works (a system Python, no permission to write,
no pip) Inkmill explains what to type instead.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .plugins import parse_version

REPOSITORY = "https://github.com/aarondodd/inkmill.git"
DEFAULT_URL = "https://raw.githubusercontent.com/aarondodd/inkmill/main/"
VERSION_FILE = "src/inkmill/__init__.py"
CHANGELOG_FILE = "CHANGELOG.md"
TIMEOUT = 20
INSTALL_TIMEOUT = 900
DAY = 24 * 60 * 60
MAX_NOTE_LINES = 40


class UpdateError(Exception):
    """The update source could not be read, or an install failed."""


@dataclass
class Release:
    version: str
    notes: str = ""

    def newer_than(self, current: str = __version__) -> bool:
        return is_newer(self.version, current)


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    if new is None or old is None:
        return False
    return new > old


def source_url(table: dict[str, Any] | None = None) -> str:
    """The folder URL the version and changelog are read from."""
    url = os.environ.get("INKMILL_UPDATE_URL") or str((table or {}).get("url") or "") or DEFAULT_URL
    return url if url.endswith("/") else url + "/"


def _read(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": f"Inkmill/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"{url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise UpdateError(f"cannot reach {url}: {reason}") from exc


def parse_version_file(text: str) -> str:
    match = re.search(r"""^__version__\s*=\s*["']([^"']+)["']""", text, re.MULTILINE)
    if not match or parse_version(match.group(1)) is None:
        raise UpdateError("the version file has no usable __version__")
    return match.group(1)


def notes_since(changelog: str, current: str = __version__) -> str:
    """The changelog sections for versions newer than ``current``."""
    sections: list[str] = []
    keep = False
    for line in changelog.splitlines():
        if re.match(r"^#\s", line):
            keep = False
            continue
        heading = re.match(r"^##\s+v?(\S+)", line)
        if heading:
            keep = is_newer(heading.group(1), current)
            if keep:
                sections.append(re.sub(r"\s*\(unreleased\)\s*$", "", line.lstrip("# ").strip()))
            continue
        if keep:
            sections.append(line)
    lines = "\n".join(sections).strip().splitlines()
    if len(lines) > MAX_NOTE_LINES:
        lines = lines[:MAX_NOTE_LINES] + ["...", "(the full list is in CHANGELOG.md)"]
    return "\n".join(lines)


def fetch_release(url: str | None = None, current: str = __version__) -> Release:
    base = url or source_url()
    version = parse_version_file(_read(base + VERSION_FILE))
    try:
        notes = notes_since(_read(base + CHANGELOG_FILE), current)
    except UpdateError:
        notes = ""
    return Release(version, notes)


# -- how Inkmill was installed ------------------------------------------------


@dataclass
class Method:
    """How to update this installation."""

    kind: str  # "pipx", "pip", "source" or "unknown"
    label: str  # for people, as in "pipx" or "pip (user site-packages)"
    command: list[str] | None = None  # what Inkmill would run
    manual: list[str] = field(default_factory=list)  # what a person types instead
    automatic: bool = False  # Inkmill can run the command while it is open
    deferred: bool = False  # it can run once Inkmill has closed (Windows)
    reason: str = ""  # why it is not automatic

    @property
    def possible(self) -> bool:
        return self.automatic or self.deferred


def _direct_url() -> dict[str, Any] | None:
    try:
        text = importlib.metadata.distribution("inkmill").read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return None
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _dist_folder() -> Path | None:
    try:
        return Path(str(importlib.metadata.distribution("inkmill").locate_file(""))).resolve()
    except (importlib.metadata.PackageNotFoundError, OSError):
        return None


def _externally_managed() -> bool:
    if sys.prefix != sys.base_prefix:
        return False
    stdlib = sysconfig.get_path("stdlib")
    return bool(stdlib) and (Path(stdlib) / "EXTERNALLY-MANAGED").exists()


def _user_site() -> Path | None:
    try:
        import site

        return Path(site.getusersitepackages()).resolve()
    except Exception:
        return None


def show_command(argv: list[str], windows: bool | None = None) -> str:
    windows = sys.platform == "win32" if windows is None else windows
    return subprocess.list2cmdline(argv) if windows else shlex.join(argv)


def _source_folder(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.request.url2pathname(parsed.path) if parsed.scheme == "file" else url


def detect(
    *,
    direct: dict[str, Any] | None = None,
    prefix: str | None = None,
    executable: str | None = None,
    windows: bool | None = None,
    which: Callable[[str], str | None] = shutil.which,
    has_pip: bool | None = None,
    externally_managed: bool | None = None,
    dist_folder: Path | None = None,
    user_site: Path | None = None,
    writable: Callable[[Path], bool] | None = None,
    venv: bool | None = None,
) -> Method:
    """Work out how this Inkmill was installed and how to update it.

    Every argument defaults to the running interpreter; tests pass their own.
    """
    direct = _direct_url() if direct is None else direct
    prefix = sys.prefix if prefix is None else prefix
    executable = sys.executable if executable is None else executable
    windows = sys.platform == "win32" if windows is None else windows
    has_pip = importlib.util.find_spec("pip") is not None if has_pip is None else has_pip
    externally_managed = _externally_managed() if externally_managed is None else externally_managed
    dist_folder = _dist_folder() if dist_folder is None else dist_folder
    user_site = _user_site() if user_site is None else user_site
    writable = writable or (lambda p: os.access(p, os.W_OK))
    venv = sys.prefix != sys.base_prefix if venv is None else venv

    url = str(direct.get("url", "")) if direct else ""
    vcs = direct.get("vcs_info") if direct else None
    if direct and (direct.get("dir_info", {}).get("editable") or (url.startswith("file:") and not vcs)):
        folder = _source_folder(url)
        return Method(
            "source",
            "a source folder",
            manual=[f'cd "{folder}"', "git pull", show_command([executable, "-m", "pip", "install", "-e", "."], windows)],
            reason=f"Inkmill runs from the source folder {folder}, so update it with git.",
        )

    pinned = False
    if isinstance(vcs, dict):
        pinned = bool(vcs.get("requested_revision"))
        spec = f"git+{url}"
    else:
        spec = "inkmill"

    pipx_meta = Path(prefix) / "pipx_metadata.json"
    if pipx_meta.exists():
        # pipx upgrade reinstalls from the spec pipx recorded, so a branch or
        # tag named there wins over what is installed now.
        pinned = pinned or _pipx_pinned(pipx_meta)
        pipx = which("pipx")
        argv = ["upgrade", "inkmill"] if not pinned else ["runpip", "inkmill", "install", "--upgrade", spec]
        method = Method("pipx", "pipx", manual=[show_command(["pipx", *argv], windows)])
        if pinned:
            method.reason = "It was installed from a branch or tag, so the update replaces that with the main branch."
        if pipx is None:
            method.reason = "Inkmill was installed with pipx, but the pipx program is not on the PATH."
            return method
        method.command = [pipx, *argv]
        return _finish(method, windows)

    where, user = "pip", []
    if not venv and dist_folder is not None and user_site is not None and _is_within(dist_folder, user_site):
        where, user = "pip (user site-packages)", ["--user"]
    elif venv:
        where = "pip (virtual environment)"
    argv = [executable, "-m", "pip", "install", "--upgrade", *user, spec]
    method = Method("pip", where, manual=[show_command(argv, windows)])
    if not has_pip:
        method.reason = "pip is not available to this Python, so update Inkmill the way you installed it."
        return method
    if externally_managed and not user:
        method.reason = "This Python is managed by your system's package manager, which does not let pip change it. Update Inkmill the way you installed it."
        return method
    if dist_folder is not None and not writable(dist_folder):
        method.reason = f"You do not have permission to change {dist_folder}. Run the command as the user who installed Inkmill."
        return method
    method.command = argv
    return _finish(method, windows)


def _pipx_pinned(path: Path) -> bool:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))["main_package"]["package_or_url"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return bool(re.search(r"git\+\S+@[^/@\s]+$", str(spec).strip()))


def _is_within(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def _finish(method: Method, windows: bool) -> Method:
    if windows:
        method.deferred = True
        method.reason = (
            (method.reason + " " if method.reason else "")
            + "Windows keeps Inkmill's files locked while it runs, so the update runs in a new window after Inkmill closes."
        )
    else:
        method.automatic = True
    return method


# -- installing -----------------------------------------------------------------


def install(method: Method) -> str:
    """Run the update command and return its output; raises UpdateError on failure."""
    if not method.command:
        raise UpdateError(method.reason or "Inkmill cannot update this installation itself.")
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    try:
        done = subprocess.run(
            method.command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=INSTALL_TIMEOUT,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError(f"cannot run {show_command(method.command)}: {exc}") from exc
    output = (done.stdout + done.stderr).strip()
    if done.returncode != 0:
        tail = "\n".join(output.splitlines()[-15:])
        raise UpdateError(f"the update command failed (exit {done.returncode}):\n{tail}")
    return output


def installed_version(executable: str | None = None) -> str:
    """The Inkmill version now installed, asked of a fresh interpreter.

    The running process still has the old modules loaded, so its own
    ``__version__`` cannot tell whether an install worked.
    """
    code = "import importlib.metadata as m; print(m.version('inkmill'))"
    try:
        done = subprocess.run(
            [executable or sys.executable, "-c", code],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def powershell_quote(arg: str) -> str:
    return "'" + arg.replace("'", "''") + "'"


def deferred_script(method: Method, pid: int) -> str:
    """PowerShell that waits for Inkmill to close, then runs the update."""
    assert method.command
    call = "& " + " ".join(powershell_quote(a) for a in method.command)
    return (
        f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue; "
        "Write-Host 'Updating Inkmill...'; "
        f"{call}; "
        "if ($LASTEXITCODE -eq 0) { Write-Host ''; Write-Host 'Inkmill is updated. Start it again with: inkmill' } "
        "else { Write-Host ''; Write-Host 'The update failed. The messages above say why.' }; "
        "Read-Host 'Press Enter to close this window'"
    )


def start_deferred(method: Method, pid: int | None = None) -> None:
    """Open a console window that updates Inkmill once process ``pid`` ends (Windows)."""
    script = deferred_script(method, pid or os.getpid())
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            creationflags=flags,
            close_fds=True,
        )
    except OSError as exc:
        raise UpdateError(f"cannot start PowerShell: {exc}") from exc


# -- remembering checks -----------------------------------------------------------


def due(state: dict[str, Any], mode: str, now: float) -> bool:
    """Whether a startup check should run, given [updates] check = mode."""
    if mode == "off":
        return False
    if mode == "startup":
        return True
    last = state.get("checked")
    return not isinstance(last, (int, float)) or now - last >= DAY


def describe(release: Release | None, method: Method, current: str = __version__) -> str:
    """The text of the Check for Updates box."""
    lines: list[str] = []
    if release is None or not release.newer_than(current):
        lines.append(f"Inkmill {current} is the newest version.")
    else:
        lines.append(f"Inkmill {release.version} is available. You have {current}.")
        if release.notes:
            lines += ["", "What's new:", "", release.notes]
        lines += ["", f"Installed with: {method.label}"]
        if method.automatic:
            lines.append("Inkmill can install the update now. Your documents stay open until you restart.")
        elif method.deferred:
            lines.append(method.reason)
        else:
            lines += ["", method.reason, "", "To update, run:", ""] + [f"  {line}" for line in method.manual]
    return "\n".join(lines)

