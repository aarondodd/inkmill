import urllib.error
import urllib.request

import pytest

from inkmill import system
from inkmill.system import PreviewServer, open_in_browser


@pytest.fixture
def desktop(monkeypatch):
    monkeypatch.setattr(system, "is_termux", lambda: False)
    monkeypatch.setattr(system, "is_wsl", lambda: False)
    opened = []
    monkeypatch.setattr(system.webbrowser, "open", lambda url: opened.append(url) or True)
    return opened


@pytest.fixture
def server(tmp_path):
    srv = PreviewServer(tmp_path)
    yield srv
    srv.close()


def test_desktop_preview_opens_a_loopback_address(desktop, server):
    page = server.folder / "preview-1.html"
    page.write_text("<p>hello</p>", encoding="utf-8")

    assert open_in_browser(page, server) == "webbrowser"

    (url,) = desktop
    assert url.startswith("http://127.0.0.1:")
    assert url.endswith(f"/{server.folder.name}/preview-1.html")
    with urllib.request.urlopen(url) as reply:
        assert reply.read() == b"<p>hello</p>"


def test_preview_folder_is_random_and_not_listed(server):
    other = PreviewServer(server.root.parent / "other")
    assert other.folder.name != server.folder.name
    assert len(server.folder.name) >= 16
    (server.folder / "preview-1.html").write_text("x", encoding="utf-8")
    base = f"http://127.0.0.1:{server.port}"
    for path in ("/", f"/{server.folder.name}/"):
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + path)
        assert err.value.code == 404


def test_without_a_server_the_file_url_is_used(desktop, tmp_path):
    page = tmp_path / "page.html"
    page.write_text("x", encoding="utf-8")
    open_in_browser(page)
    assert desktop == [page.resolve().as_uri()]


def test_wsl_still_opens_the_file(monkeypatch, server):
    monkeypatch.setattr(system, "is_termux", lambda: False)
    monkeypatch.setattr(system, "is_wsl", lambda: True)
    monkeypatch.setattr(system.shutil, "which", lambda name: "/usr/bin/wslview" if name == "wslview" else None)
    ran = []
    monkeypatch.setattr(system, "_run_detached", lambda argv: ran.append(argv) or True)
    page = server.folder / "preview-1.html"
    page.write_text("x", encoding="utf-8")
    assert open_in_browser(page, server) == "wslview"
    assert ran == [["wslview", str(page.resolve())]]
