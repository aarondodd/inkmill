"""Platform detection and "open in the default browser".

Desktop platforms use :mod:`webbrowser` with a ``file://`` URL. Two cases need
more care:

* Termux on Android. Browsers cannot read files inside Termux's private
  storage, so Inkmill serves the preview over a loopback HTTP server and hands
  the URL to ``termux-open-url`` (from the ``termux-tools`` package).
* WSL. ``webbrowser`` usually finds no browser; ``wslview`` (wslu) or
  ``explorer.exe`` open the Windows default browser instead.
"""

from __future__ import annotations

import functools
import os
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


class PreviewServer:
    """A loopback-only static file server for one directory, started lazily."""

    def __init__(self, root: Path) -> None:
        self.root = root
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
