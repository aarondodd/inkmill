"""Export via Pandoc, Binder 1.1, the AI Assistant and plugin requirements."""

import json
import shutil
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from textual.widgets import Input, OptionList

from inkmill import frontmatter
from inkmill.plugins import Manifest, Requirement
from pluginhelp import app_with, load_module, wait_for

convert = load_module("pandoc", "convert")
clip = load_module("binder", "clip")
client = load_module("ai", "client")
binder_model = load_module("binder", "model")

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")


# -- requirements ------------------------------------------------------------------

def test_requirements_from_manifest(tmp_path):
    path = tmp_path / "plugin.toml"
    path.write_text(
        'id = "x"\nname = "X"\nversion = "1"\nexternal = ["git"]\n'
        '[[requires]]\ncommand = "surely-not-installed-zz"\npurpose = "testing"\n'
        'install = { linux = "apt install zz", windows = "winget install zz", macos = "brew install zz", termux = "pkg install zz" }\n'
        '[[requires]]\nany_of = ["surely-not-a", "python3", "python"]\noptional = true\n'
    )
    m = Manifest.load(path)
    names = [r.name for r in m.requires]
    assert names == ["surely-not-installed-zz", "surely-not-a or python3 or python", "git"]
    missing = m.requires[0]
    assert missing.found() is None and "install zz" in missing.install_hint()
    assert m.requires[1].found() is not None
    from inkmill.pluginmanager import check_requirements, describe_missing

    required, optional = check_requirements(m)
    assert [r.command for r in required][0] == "surely-not-installed-zz"
    assert "for testing" in describe_missing(required)


async def test_manager_warns_before_installing_with_missing_program(tmp_path):
    from inkmill.app import InkmillApp
    from inkmill.config import Settings, State
    from test_pluginmanager import write_source

    src = write_source(tmp_path)
    toml = src / "plugins" / "hello" / "plugin.toml"
    toml.write_text(toml.read_text() + '[[requires]]\ncommand = "surely-not-installed-zz"\npurpose = "testing"\n')
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import build_plugin_index

    sys.path.pop(0)
    (src / "plugins" / "index.json").write_text(json.dumps(build_plugin_index.build(src / "plugins")))
    settings = Settings(restore_session=False, recovery_interval=0, plugin_manager={"source": "local", "local_path": str(src)})
    app = InkmillApp(settings=settings, state=State(tmp_path / "s.json"), plugin_dir=tmp_path / "installed")
    async with app.run_test(size=(120, 30)) as pilot:
        app.run_command("view.plugins")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "PluginManagerScreen" and app.screen.rows)
        await pilot.press("1")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog")
        assert "surely-not-installed-zz" in str(app.screen.message)
        await pilot.press("c")
        await pilot.pause(0.2)
        assert not (tmp_path / "installed" / "hello").exists()


# -- Pandoc --------------------------------------------------------------------------

@needs_pandoc
def test_manuscript_reference_and_exports(tmp_path):
    ref = convert.manuscript_reference(tmp_path / "cache")
    styles = zipfile.ZipFile(ref).read("word/styles.xml").decode()
    assert 'w:line="480"' in styles and "Courier New" in styles and "pageBreakBefore" in styles
    md = "---\ntitle: T\n---\n" + convert.title_page({"title": "T", "author": "A", "contact": ["x@y.z"]}, 1234) + "# One\n\nText.[^1]\n\n[^1]: Note.\n"
    out = tmp_path / "m.docx"
    convert.export(md, next(f for f in convert.FORMATS if f.id == "manuscript"), out, resource_dir=tmp_path, reference_doc=ref)
    plain = convert.run([str(out), "-t", "plain"])
    assert "About 1,200 words" in plain and "One" in plain
    for fid in ("docx", "odt", "epub", "plain"):
        fmt = next(f for f in convert.FORMATS if f.id == fid)
        target = tmp_path / f"t{fmt.extension}"
        convert.export(md, fmt, target, resource_dir=tmp_path)
        assert target.stat().st_size > 0


@needs_pandoc
def test_import_docx(tmp_path):
    fmt = next(f for f in convert.FORMATS if f.id == "docx")
    source = tmp_path / "in.docx"
    convert.export("# Heading\n\nSome *emphasis*.\n", fmt, source, resource_dir=tmp_path)
    text = convert.import_file(source)
    assert "# Heading" in text and "*emphasis*" in text


# -- Binder 1.1 --------------------------------------------------------------------------

def test_clipper_keeps_main_text():
    html = ("<html><head><title>Ships</title></head><body><nav>menu</nav><article><h2>Rigging</h2>"
            "<p>A <strong>square</strong> rig " + "word " * 60 + "</p><blockquote><p>Quote.</p></blockquote>"
            "<ul><li>Fore</li></ul></article><footer>x</footer></body></html>")
    title, md = clip.to_markdown(html, "https://e.com/")
    assert title == "Ships"
    assert "## Rigging" in md and "**square**" in md and "> Quote." in md and "- Fore" in md
    assert "menu" not in md


def test_research_links_keep_urls(tmp_path):
    binder = tmp_path / "book.md"
    text = "---\ntitle: Book\n---\n"
    text = binder_model.add_relation(text, binder, "research", tmp_path / "research" / "ships.md")
    text = binder_model.add_relation(text, binder, "research", "https://example.com/ships")
    links = binder_model.read_links(binder, text)
    assert links.research[0].name == "ships.md"
    assert links.research_urls == ["https://example.com/ships"]
    text = binder_model.remove_relation(text, binder, "research", "https://example.com/ships")
    assert "example.com" not in text and "research/ships.md" in text


async def test_binder_outline_status_and_service(tmp_path):
    from test_binder import novel

    binder, chapters = novel(tmp_path)
    app = app_with(tmp_path, "binder", paths=[chapters / "chapter-02.md"])
    async with app.run_test(size=(120, 30)) as pilot:
        service = app.services["binder"]
        assert service.binder_for(chapters / "chapter-02.md") == binder_model.norm(binder)
        assert "Chapter 1 text" in service.manuscript_markdown(binder)
        app.run_command("binder.outline")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "BinderOutlineScreen")
        await pilot.press("s")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ChoiceDialog")
        option_list = app.screen.query_one(OptionList)
        option_list.highlighted = next(i for i, o in enumerate(option_list._options) if o.id == "revised")
        await pilot.press("enter")
        await pilot.pause(0.3)
        first = (chapters / "chapter-01.md").read_text()
        assert frontmatter.read(first)["status"] == "revised"
        await pilot.press("escape")


async def test_new_research_note_is_listed(tmp_path):
    from test_binder import novel

    binder, chapters = novel(tmp_path)
    app = app_with(tmp_path, "binder", paths=[chapters / "chapter-01.md"])
    async with app.run_test(size=(120, 30)) as pilot:
        app.run_command("binder.note")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "InputDialog")
        app.screen.query_one(Input).value = "Ship types"
        await pilot.press("enter")
        note = tmp_path / "research" / "ship-types.md"
        assert await wait_for(pilot, lambda: note.exists())
        assert "research/ship-types.md" in binder.read_text()
        assert frontmatter.read(note.read_text())["parent"] == "../the-long-night.md"


# -- AI Assistant -------------------------------------------------------------------------

class FakeAI(BaseHTTPRequestHandler):
    requests: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeAI.requests.append((self.path, dict(self.headers), body))
        if self.headers.get("x-api-key") == "bad":
            self.send_response(401)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "invalid x-api-key"}}).encode())
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        if self.path.endswith("/v1/messages"):
            for piece in ("Tighter ", "version."):
                event = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}}
                self.wfile.write(f"event: content_block_delta\ndata: {json.dumps(event)}\n\n".encode())
        else:
            for piece in ("One\n---\n", "Two\n---\nThree"):
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': piece}}]})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_ai():
    FakeAI.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_ai_client_streams_both_kinds(fake_ai):
    pieces = []
    claude = client.Provider("anthropic", "C", "anthropic", fake_ai, "claude-sonnet-5-5", "")
    reply = client.stream(claude, "k", "sys", [{"role": "user", "content": "hi"}], pieces.append, context="BOOK")
    assert reply == "Tighter version." and pieces == ["Tighter ", "version."]
    path, headers, body = FakeAI.requests[-1]
    assert body["system"][1]["cache_control"] == {"type": "ephemeral"} and body["stream"] is True
    local = client.Provider("ollama", "O", "openai", fake_ai, "llama3.1", needs_key=False)
    assert client.stream(local, None, "sys", [{"role": "user", "content": "hi"}], lambda t: None) == "One\n---\nTwo\n---\nThree"
    with pytest.raises(client.AIError, match="refused the API key"):
        client.stream(claude, "bad", "sys", [{"role": "user", "content": "hi"}], lambda t: None)


def test_ai_key_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = client.PRESETS["anthropic"]
    assert client.load_key(tmp_path, p) is None
    path = client.save_key(tmp_path, p, "  sk-test \n")
    assert client.load_key(tmp_path, p) == "sk-test"
    import os
    import sys

    if sys.platform != "win32":
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert client.load_key(tmp_path, p) == "from-env"


async def test_ai_rewrite_picks_an_alternative(tmp_path, fake_ai):
    doc = tmp_path / "d.md"
    doc.write_text("A long and winding sentence.\n")
    ai_settings = {"provider": "ollama", "base_url": fake_ai, "model": "llama3.1"}
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": ai_settings})
    async with app.run_test(size=(120, 30)) as pilot:
        editor = app.active_editor
        editor.select_range((0, 0), (0, 28))
        app.run_command("ai.rewrite")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "InputDialog")
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog")  # first use asks
        await pilot.press("a")
        panel = None
        assert await wait_for(pilot, lambda: app.panel.visible and app.panel.content.done)
        await pilot.press("2")
        assert await wait_for(pilot, lambda: app.active_document.text == "Two\n")
        assert "127.0.0.1" in str(app.settings.plugins["ai"]["consented"])


async def test_ai_history_is_kept_in_the_project_for_other_providers(tmp_path, fake_ai):
    doc = tmp_path / "d.md"
    doc.write_text("A long and winding sentence.\n")
    ai_settings = {"provider": "ollama", "base_url": fake_ai, "model": "llama3.1"}
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": ai_settings})
    async with app.run_test(size=(120, 30)) as pilot:
        app.run_command("ai.history")
        await pilot.pause(0.2)
        assert type(app.screen).__name__ != "TurnList"  # nothing yet
        previous = None
        for n in range(2):
            app.run_command("ai.summarize")
            if n == 0:
                assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog")
                await pilot.press("a")
            assert await wait_for(pilot, lambda: app.panel.visible and app.panel.content is not previous
                                  and app.panel.content.done)
            previous = app.panel.content
        panel = app.panel.content
        assert len(panel.entries) == 2 and panel.index == 1
        assert panel.entries[1].label == "Summarize" and panel.entries[1].about == "d.md"
        assert panel.entries[1].request == "(About the whole document.)"  # the sent text is not repeated
        await pilot.press("q")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "InputDialog")
        app.screen.query_one("Input").value = "Shorter?"
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: app.panel.content is not panel and app.panel.content.done)
        assert [e.label for e in app.panel.content.entries] == ["Summarize", "Summarize", "Follow-up"]

    # The turns outlive the app: they are in the document's folder.
    assert (tmp_path / ".inkmill" / "ai-conversation.jsonl").is_file()
    again = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": ai_settings})
    async with again.run_test(size=(120, 30)) as pilot:
        again.run_command("ai.history")
        assert await wait_for(pilot, lambda: type(again.screen).__name__ == "TurnList")
        assert again.screen.query_one(OptionList).option_count == 3


async def test_ai_history_stays_in_memory_when_the_log_is_off(tmp_path, fake_ai):
    doc = tmp_path / "d.md"
    doc.write_text("A sentence.\n")
    ai_settings = {"provider": "ollama", "base_url": fake_ai, "model": "llama3.1", "keep_history": False,
                   "consented": ["127.0.0.1:" + fake_ai.rsplit(":", 1)[1].split("/")[0]]}
    app = app_with(tmp_path, "ai", paths=[doc], plugins={"ai": ai_settings})
    async with app.run_test(size=(120, 30)) as pilot:
        app.run_command("ai.summarize")
        if await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog", timeout=1):
            await pilot.press("a")
        assert await wait_for(pilot, lambda: app.panel.visible and app.panel.content.done)
        app.run_command("ai.history")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "TurnList")
    assert not (tmp_path / ".inkmill").exists()
