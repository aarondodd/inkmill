"""Platform detection and "open in the default browser".

Previews are served over a loopback HTTP server and opened by their
``http://127.0.0.1`` address, for two reasons. A web address goes to the
default web browser, while a local ``.html`` file goes to whatever app owns
that file type, which can be a different browser (Kubuntu maps it to
Firefox). And sandboxed browsers (snap, Flatpak, Android) cannot read files in
Inkmill's temporary folder: a snap has its own private ``/tmp``, and Termux's
storage is private to Termux.

* Termux hands the address to ``termux-open-url`` (``termux-tools``).
* WSL opens the file with ``wslview`` (wslu) or ``explorer.exe``, since whether
  a Windows browser can reach WSL's loopback depends on its networking mode.
* Elsewhere :mod:`webbrowser` opens the address, falling back to a
  ``file://`` URL if the server cannot start.
"""

from __future__ import annotations

import functools
import os
import secrets
import shutil
import subprocess
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def is_termux() -> bool:
    return "TERMUX_VERSION" in os.environ or "com.termux" in os.environ.get("PREFIX", "")


@functools.cache
def is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def platform_name() -> str:
    if is_termux():
        return "termux"
    if is_wsl():
        return "wsl"
    return sys.platform


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def list_directory(self, path):  # noqa: ANN001
        # No listings, so the random folder name cannot be discovered.
        self.send_error(404)
        return None


class PreviewServer:
    """A loopback-only static file server, started lazily.

    Files go in :attr:`folder`, a randomly named folder under ``root``, so
    another user on the machine cannot guess a preview's address.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.folder = root / secrets.token_urlsafe(16)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._server: ThreadingHTTPServer | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            handler = functools.partial(_QuietHandler, directory=str(self.root))
            self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            thread.start()
        return self._server.server_address[1]

    def url_for(self, path: Path) -> str:
        rel = path.resolve().relative_to(self.root.resolve()).as_posix()
        return f"http://127.0.0.1:{self.port}/{rel}"

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def _run_detached(argv: list[str]) -> bool:
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=(os.name != "nt"),
        )
        return True
    except OSError:
        return False


def open_in_browser(path: Path, server: PreviewServer | None = None) -> str:
    """Open ``path`` in the default browser. Returns how it was opened.

    Raises RuntimeError when no method worked.
    """
    path = path.resolve()
    if is_termux():
        opener = shutil.which("termux-open-url")
        if opener and server is not None:
            if _run_detached([opener, server.url_for(path)]):
                return "termux-open-url"
        opener = shutil.which("termux-open")
        if opener and _run_detached([opener, str(path)]):
            return "termux-open"
        raise RuntimeError("install termux-tools to open the browser (pkg install termux-tools)")
    if is_wsl():
        for argv in (["wslview", str(path)],):
            if shutil.which(argv[0]) and _run_detached(argv):
                return argv[0]
        wslpath = shutil.which("wslpath")
        if wslpath and shutil.which("explorer.exe"):
            win = subprocess.run([wslpath, "-w", str(path)], capture_output=True, text=True).stdout.strip()
            if win and _run_detached(["explorer.exe", win]):
                return "explorer.exe"
    elif server is not None:
        try:
            url = server.url_for(path)
        except (OSError, ValueError):
            url = None
        if url and webbrowser.open(url):
            return "webbrowser"
    if webbrowser.open(path.as_uri()):
        return "webbrowser"
    raise RuntimeError("no web browser could be found")


def open_folder(path: Path) -> None:
    """Reveal a folder in the system file manager (best effort)."""
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        _run_detached(["open", str(path)])
    elif is_termux():
        _run_detached(["termux-open", str(path)])
    else:
        _run_detached(["xdg-open", str(path)])


def open_url(url: str) -> str:
    """Open a web address in the default browser. Returns how it was opened.

    Raises RuntimeError when no method worked.
    """
    if is_termux():
        opener = shutil.which("termux-open-url")
        if opener and _run_detached([opener, url]):
            return "termux-open-url"
        raise RuntimeError("install termux-tools to open links (pkg install termux-tools)")
    if is_wsl() and shutil.which("wslview") and _run_detached(["wslview", url]):
        return "wslview"
    if webbrowser.open(url):
        return "webbrowser"
    raise RuntimeError("no web browser could be found")


def open_file(path: Path) -> str:
    """Open a file (a PDF, an image) in the system's default app."""
    path = path.resolve()
    if is_termux():
        opener = shutil.which("termux-open")
        if opener and _run_detached([opener, str(path)]):
            return "termux-open"
        raise RuntimeError("install termux-tools to open files (pkg install termux-tools)")
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return "startfile"
    if sys.platform == "darwin":
        if _run_detached(["open", str(path)]):
            return "open"
    if is_wsl() and shutil.which("wslview") and _run_detached(["wslview", str(path)]):
        return "wslview"
    if shutil.which("xdg-open") and _run_detached(["xdg-open", str(path)]):
        return "xdg-open"
    return open_in_browser(path)
