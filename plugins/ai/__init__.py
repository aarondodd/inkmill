"""AI Assistant: ask about your writing, opt in, one request at a time.

Nothing is sent until you run an AI command, and the first request to each
server asks for your permission. Replies stream into the side panel and
never change your text on their own: I inserts the reply at the cursor, R
replaces the selection, 1 to 3 pick one of several rewrites, Q asks a
follow-up, C copies.

Works with Claude (an Anthropic API key), a local Ollama server (no key, no
network), or any OpenAI-compatible server.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from rich.markdown import Markdown
from rich.text import Text
from textual import events
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from inkmill import frontmatter
from inkmill.config import config_dir
from inkmill.screens.dialogs import ChoiceDialog, ConfirmDialog, InputDialog

from . import client

SYSTEM = (
    "You are a writing assistant inside Inkmill, a Markdown word processor. The writer stays in charge: "
    "give specific, honest feedback and suggestions, quote the passages you mean, and do not rewrite "
    "their work unless they ask. Answer in Markdown. Be concise."
)
HINT_BASE = "Q follow up  C copy  Esc close"
SPLIT = re.compile(r"^\s*-{3,}\s*$", re.MULTILINE)


class ReplyPanel(Vertical):
    """A streaming reply with keys to use it."""

    DEFAULT_CSS = """
    ReplyPanel { height: 1fr; }
    ReplyPanel > VerticalScroll { height: 1fr; padding: 0 1; }
    """

    can_focus = True

    def __init__(self, plugin, *, can_replace: bool, choices: bool) -> None:
        super().__init__()
        self.plugin = plugin
        self.can_replace = can_replace
        self.choices = choices
        self.text = ""
        self.done = False

    def compose(self):
        with VerticalScroll():
            yield Static(Text("Waiting for the reply...", style="italic"), id="ai-reply")

    def add(self, piece: str) -> None:
        self.text += piece
        self.query_one("#ai-reply", Static).update(Text(self.text))
        self.query_one(VerticalScroll).scroll_end(animate=False)

    def finish(self, error: str | None = None) -> None:
        self.done = True
        reply = self.query_one("#ai-reply", Static)
        if error:
            reply.update(Text(f"{self.text}\n\n{error}" if self.text else error, style="bold"))
            return
        reply.update(Markdown(self.text) if self.text.strip() else Text("(no reply)", style="italic"))

    def alternatives(self) -> list[str]:
        return [part.strip() for part in SPLIT.split(self.text) if part.strip()]

    def on_key(self, event: events.Key) -> None:
        key = (event.character or "").lower()
        if not self.done or not key:
            return
        handled = True
        if key == "i":
            self.plugin.insert(self.text.strip())
        elif key == "r" and self.can_replace:
            self.plugin.replace(self.text.strip())
        elif key in "123" and self.choices:
            options = self.alternatives()
            index = int(key) - 1
            if index < len(options):
                self.plugin.replace(_strip_number(options[index]))
        elif key == "c":
            self.app.copy_to_clipboard(self.text)
            self.app.status.flash("Copied the reply.")
        elif key == "q":
            self.plugin.follow_up()
        else:
            handled = False
        if handled:
            event.stop()


def _strip_number(text: str) -> str:
    return re.sub(r"^\s*(?:\d+[.)]|#+\s*\d+[.)]?|Option\s+\d+:?)\s*", "", text).strip()


def register(api):
    app = api.app
    state: dict = {"cancel": None, "conversation": [], "context": "", "selection": None, "panel": None}

    def table() -> dict:
        return api.settings

    def provider() -> client.Provider:
        return client.provider_from_settings(table())

    def has_doc(_app) -> bool:
        return app.active_editor is not None

    async def ready_to_send(p: client.Provider) -> bool:
        consented = list(table().get("consented", []))
        if p.host not in consented:
            local = p.host.startswith(("localhost", "127.0.0.1", "[::1]"))
            where = "a server on this computer" if local else p.host
            answer = await app.push_screen_wait(ConfirmDialog(
                "Send text to an AI?",
                f"AI commands send the text you choose to {where} ({p.name}, model {p.model or 'not set'}).\n"
                "Nothing is sent otherwise. Allow this server?",
                (("yes", "&Allow"), ("no", "&Cancel")),
            ))
            if answer != "yes":
                return False
            consented.append(p.host)
            table()["consented"] = consented
            api.save_settings()
        if p.needs_key and not client.load_key(config_dir(), p):
            await set_key(app)
            return client.load_key(config_dir(), p) is not None
        return True

    # -- sending -----------------------------------------------------------------

    async def ask(prompt: str, title: str, *, context: str = "", can_replace: bool = False, choices: bool = False,
                  max_tokens: int | None = None) -> None:
        p = provider()
        if not await ready_to_send(p):
            return
        if state["cancel"] is not None:
            state["cancel"].set()
        state["conversation"] = [{"role": "user", "content": prompt}]
        state["context"] = context
        await run(title, can_replace=can_replace, choices=choices, max_tokens=max_tokens)

    async def run(title: str, *, can_replace: bool, choices: bool, max_tokens: int | None = None) -> None:
        p = provider()
        panel = ReplyPanel(plugin, can_replace=can_replace, choices=choices)
        state["panel"] = panel
        hints = ["I insert"] + (["R replace"] if can_replace else []) + (["1-3 pick"] if choices else []) + [HINT_BASE]
        await api.show_panel(panel, f"AI: {title}", "  ".join(hints))
        cancel = threading.Event()
        state["cancel"] = cancel

        def on_text(piece: str) -> None:
            app.call_from_thread(panel.add, piece)

        try:
            reply = await api.run_in_thread(
                client.stream, p, client.load_key(config_dir(), p), SYSTEM, state["conversation"], on_text,
                context=state["context"], max_tokens=int(max_tokens or table().get("max_tokens", 2048)), cancel=cancel,
            )
        except client.AIError as exc:
            panel.finish(f"Request failed: {exc}")
            return
        if cancel.is_set():
            return
        state["conversation"].append({"role": "assistant", "content": reply})
        panel.finish()

    # -- using the reply ---------------------------------------------------------

    class Plugin:
        def insert(self, text: str) -> None:
            editor = app.active_editor
            if editor is None:
                return
            editor.insert(text)
            app.status.flash("Inserted the reply. Ctrl+Z undoes it.")

        def replace(self, text: str) -> None:
            editor = app.active_editor
            saved = state["selection"]
            if editor is None or saved is None:
                return
            doc_id, start, end, original = saved
            if editor.doc.id != doc_id or editor.document.get_text_range(start, end) != original:
                app.notify("The selected text changed since you asked; use I to insert instead.", severity="warning")
                return
            editor.replace(text, start, end)
            new_end = editor.location_of(editor.index_of(start) + len(text))
            state["selection"] = (doc_id, start, new_end, text)
            app.status.flash("Replaced the selection. Ctrl+Z undoes it.")

        def follow_up(self) -> None:
            app.run_worker(follow_up_worker(), exit_on_error=False)

    plugin = Plugin()

    async def follow_up_worker() -> None:
        question = await app.push_screen_wait(InputDialog("Follow up", "Ask:", ""))
        if not question:
            return
        state["conversation"].append({"role": "user", "content": question})
        await run("follow-up", can_replace=state["selection"] is not None, choices=False)

    # -- what to send -----------------------------------------------------------

    def selection():
        editor = app.active_editor
        if editor is None or not editor.selected_text.strip():
            return None
        start, end = sorted([editor.selection.start, editor.selection.end])
        return editor.doc.id, start, end, editor.selected_text

    def document_text() -> str:
        doc = app.active_document
        return doc.text if doc else ""

    def binder_context(path: Path | None) -> tuple[str, str] | None:
        binder = api.service("binder")
        if binder is None or path is None:
            return None
        holder = binder.binder_for(path)
        if holder is None:
            return None
        parts = [f"# Manuscript: {binder.title(holder)}\n\n{binder.manuscript_markdown(holder)}"]
        files, urls = binder.research(holder)
        for note in files[:200]:
            text = binder.read(note)
            if text:
                parts.append(f"# Research note: {note.name}\n\n{text}")
        if urls:
            parts.append("# Research links\n\n" + "\n".join(f"- {u}" for u in urls))
        limit = int(table().get("max_context_chars", 600_000))
        context = "\n\n".join(parts)
        if len(context) > limit:
            context = context[:limit] + "\n\n[cut: the manuscript is longer than max_context_chars]"
        return binder.title(holder), context

    # -- commands ------------------------------------------------------------------

    api.add_menu("ai", "&AI")

    @api.command("ai.ask", "&Ask...", menu="ai", enabled=has_doc,
                 description="Ask anything about the selection or this document")
    async def ask_cmd(app):
        sel = selection()
        state["selection"] = sel
        about = "the selected passage" if sel else "this document"
        question = await app.push_screen_wait(InputDialog("Ask the AI", f"About {about}:", ""))
        if not question:
            return
        source = sel[3] if sel else document_text()
        await ask(f"{question}\n\nThe text:\n\n{source}", "Ask", can_replace=sel is not None)

    @api.command("ai.feedback", "&Feedback", menu="ai", enabled=has_doc,
                 description="A reader's notes on the selection, or the whole chapter")
    async def feedback(app):
        sel = selection()
        state["selection"] = None
        source = sel[3] if sel else document_text()
        prompt = (
            "Give me feedback on this passage as an experienced editor would: what works, what does not, and the "
            "three changes that would help most. Consider clarity, pacing, voice, dialogue and structure, and quote "
            f"the lines you mean.\n\n{source}"
        )
        await ask(prompt, "Feedback")

    @api.command("ai.rewrite", "&Rewrite Selection...", menu="ai", enabled=lambda a: selection() is not None,
                 description="Three alternatives for the selection; pick one with 1, 2 or 3")
    async def rewrite(app):
        sel = selection()
        state["selection"] = sel
        how = await app.push_screen_wait(InputDialog("Rewrite", "How? (tighter, warmer, more formal, simpler...)", "tighter"))
        if not how:
            return
        prompt = (
            f"Rewrite the passage below three different ways, {how}. Keep the meaning and the writer's voice. "
            "Reply with only the three versions, separated by lines containing just ---, without numbers or "
            f"commentary.\n\n{sel[3]}"
        )
        await ask(prompt, f"Rewrite ({how})", can_replace=True, choices=True)

    @api.command("ai.summarize", "Su&mmarize", menu="ai", enabled=has_doc)
    async def summarize(app):
        sel = selection()
        state["selection"] = None
        source = sel[3] if sel else document_text()
        await ask(f"Summarize this in a short paragraph, then list its key points.\n\n{source}", "Summary")

    @api.command("ai.synopsis", "Write &Synopsis", menu="ai", enabled=has_doc,
                 description="A one- or two-sentence synopsis, saved to the document's front matter")
    async def synopsis(app):
        doc = app.active_document
        p = provider()
        if not await ready_to_send(p):
            return
        app.status.flash("Writing a synopsis...", seconds=30)
        prompt = ("Write a synopsis of this chapter in one or two plain sentences, present tense, no preamble. "
                  f"Reply with the synopsis only.\n\n{frontmatter.split(doc.text)[1]}")
        try:
            reply = await api.run_in_thread(client.stream, p, client.load_key(config_dir(), p), SYSTEM,
                                            [{"role": "user", "content": prompt}], lambda _t: None, max_tokens=300)
        except client.AIError as exc:
            app.notify(f"Synopsis failed: {exc}", severity="error")
            return
        text = " ".join(reply.split()).strip().strip('"')
        if not text:
            return
        answer = await app.push_screen_wait(InputDialog("Synopsis", "Edit, then Enter to save it (Esc to discard):", text))
        if not answer:
            return
        binder = api.service("binder")
        if binder is not None and doc.path is not None:
            binder.set_field(doc.path, "synopsis", answer)
        else:
            app.replace_document_text(doc, frontmatter.update(doc.text, {"synopsis": answer}))
        app.status.flash("Synopsis saved.")

    @api.command("ai.continuity", "&Continuity Check", menu="ai",
                 enabled=lambda a: a.active_document is not None and a.active_document.path is not None and api.service("binder") is not None,
                 description="Names, dates, places and facts that disagree across the whole binder")
    async def continuity(app):
        found = binder_context(app.active_document.path)
        if found is None:
            app.status.flash("Continuity Check works on a binder; this document is not in one.")
            return
        title, context = found
        answer = await app.push_screen_wait(ConfirmDialog(
            "Continuity Check", f"Send the whole of {title} ({len(context):,} characters) and its research notes?"
        ))
        if answer != "yes":
            return
        state["selection"] = None
        prompt = (
            "Read the manuscript and research notes above. List every continuity problem you find: characters' "
            "names, ages, looks and relationships; dates and the order of events; places and distances; objects; "
            "and facts that contradict the research notes. For each, quote both passages and name the chapters. "
            "Group them by kind, most serious first. If you find none in a group, leave it out."
        )
        await ask(prompt, f"Continuity: {title}", context=context, max_tokens=int(table().get("max_tokens_long", 4096)))

    async def set_key(app):
        p = provider()
        if not p.needs_key:
            app.status.flash(f"{p.name} needs no key.")
            return
        hint = f" (or set {p.key_env} in your environment)" if p.key_env else ""
        key = await app.push_screen_wait(InputDialog(f"API key for {p.name}", f"Paste the key{hint}:", ""))
        if not key or not key.strip():
            return
        path = client.save_key(config_dir(), p, key)
        app.status.flash(f"Key saved to {path} (readable only by you).")

    api.command("ai.key", "Set API &Key...", menu="ai", separator=True,
                description="Stored in its own file, never in settings.toml")(set_key)

    @api.command("ai.settings", "AI Se&ttings...", menu="ai")
    async def settings(app):
        current = provider()
        choice = await app.push_screen_wait(ChoiceDialog(
            "AI Provider", [(k, f"{v.name}  ({v.base_url})") for k, v in client.PRESETS.items()], current.id
        ))
        if not choice:
            return
        preset = client.PRESETS[choice]
        same = choice == current.id
        model = await app.push_screen_wait(InputDialog("Model", f"Model name for {preset.name}:", current.model if same else preset.model))
        if model is None:
            return
        base = await app.push_screen_wait(InputDialog("Server", "Address:", current.base_url if same else preset.base_url))
        if base is None:
            return
        table()["provider"] = choice
        table()["model"] = model.strip()
        if base.strip() and base.strip() != preset.base_url:
            table()["base_url"] = base.strip()
        else:
            table().pop("base_url", None)
        api.save_settings()
        app.status.flash(f"AI: {preset.name}, {model.strip() or 'no model set'}")
