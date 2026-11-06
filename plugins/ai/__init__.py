"""AI Assistant: ask about your writing, opt in, one request at a time.

Nothing is sent until you run an AI command, and the first request to each
server asks for your permission. Replies stream into the side panel and
never change your text on their own: I inserts the reply at the cursor, R
replaces the selection, 1 to 3 pick one of several rewrites, Q asks a
follow-up, B adds the reply to the story bible, C copies.

Works with Claude Code (the claude program, on your Claude plan), Claude
through the API (an Anthropic API key), a local Ollama server (no key, no
network), or any OpenAI-compatible server.

With Claude Code, each project (a binder, or the folder of a document that is
not in one) keeps one conversation that later requests continue, so Claude
remembers earlier questions; and Claude may read the project's files itself
instead of being sent them.
"""

from __future__ import annotations

import datetime
import re
import textwrap
import threading
from dataclasses import dataclass
from pathlib import Path

from rich.markdown import Markdown
from rich.text import Text
from textual import events
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from inkmill import frontmatter
from inkmill.config import config_dir, state_dir
from inkmill.screens.dialogs import ChoiceDialog, ConfirmDialog, InputDialog, TextDialog

from . import claudecode, client

SYSTEM = (
    "You are a writing assistant inside Inkmill, a Markdown word processor. The writer stays in charge: "
    "give specific, honest feedback and suggestions, quote the passages you mean, and do not rewrite "
    "their work unless they ask. Answer in Markdown. Be concise."
)
SYSTEM_FILES = SYSTEM + (
    " You can read the writer's files with the Read, Grep and Glob tools. Read what a question needs and no "
    "more, and read a file again when asked about it, since the writer keeps editing. You cannot change "
    "files; the writer inserts your replies themselves. Each request starts with a short note naming the "
    "project folder, the document being worked on and the story bible, when there is one: the story bible "
    "holds the facts the writer has settled, so follow it."
)
BIBLE_TEMPLATE = """# Story Bible

The AI Assistant reads this file with every request. Keep the facts you have
settled here: who people are, where things are, what happened when, and how
the book should sound. In the AI reply panel, B adds a reply to the end.

## Characters

## Places

## Timeline

## Style
"""
HINT_BASE = "Q follow up  B bible  C copy  Esc close"
SPLIT = re.compile(r"^\s*-{3,}\s*$", re.MULTILINE)


class ReplyPanel(Vertical):
    """A streaming reply with keys to use it."""

    DEFAULT_CSS = """
    ReplyPanel { height: 1fr; }
    ReplyPanel > VerticalScroll { height: 1fr; padding: 0 1; }
    ReplyPanel #ai-note { color: $im-dialog-fg 70%; text-style: italic; height: auto; }
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
            yield Static("", id="ai-note")
            yield Static(Text("Waiting for the reply...", style="italic"), id="ai-reply")

    def add(self, piece: str) -> None:
        self.text += piece
        self.query_one("#ai-reply", Static).update(Text(self.text))
        self.query_one(VerticalScroll).scroll_end(animate=False)

    def note(self, line: str) -> None:
        """What Claude is doing between pieces of text (reading a chapter)."""
        self.query_one("#ai-note", Static).update(line)

    def reset(self) -> None:
        self.text = ""
        self.query_one("#ai-reply", Static).update(Text("Writing the reply...", style="italic"))

    def finish(self, error: str | None = None, text: str | None = None) -> None:
        self.done = True
        self.note("")
        if text is not None:
            self.text = text
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
        elif key == "b":
            self.plugin.add_to_bible(self.text.strip())
        elif key == "q":
            self.plugin.follow_up()
        else:
            handled = False
        if handled:
            event.stop()


def _strip_number(text: str) -> str:
    return re.sub(r"^\s*(?:\d+[.)]|#+\s*\d+[.)]?|Option\s+\d+:?)\s*", "", text).strip()


@dataclass
class Project:
    folder: Path
    binder: Path | None
    label: str


def register(api):
    app = api.app
    state: dict = {"cancel": None, "conversation": [], "prompt": "", "context": "", "selection": None, "panel": None}

    def table() -> dict:
        return api.settings

    def provider() -> client.Provider:
        return client.provider_from_settings(table())

    def is_cli() -> bool:
        return provider().kind == "cli"

    def files_on() -> bool:
        return is_cli() and bool(table().get("file_access", True))

    def has_doc(_app) -> bool:
        return app.active_editor is not None

    def sessions() -> claudecode.Sessions:
        return claudecode.Sessions(state_dir() / "ai" / "claude-code-sessions.json")

    # -- the project, its files and its story bible ------------------------------

    def project() -> Project:
        doc = app.active_document
        if doc is not None and doc.path is not None:
            path = doc.path.resolve()
            binder = api.service("binder")
            holder = binder.binder_for(path) if binder is not None else None
            if holder is not None:
                return Project(Path(holder).resolve().parent, Path(holder).resolve(), binder.title(holder))
            return Project(path.parent, None, path.parent.name or str(path.parent))
        folder = state_dir() / "ai" / "unsaved"
        folder.mkdir(parents=True, exist_ok=True)
        return Project(folder, None, "unsaved documents")

    def snapshot_dir() -> Path:
        return state_dir() / "ai" / "current"

    def rel(path: Path, proj: Project) -> str:
        try:
            return path.resolve().relative_to(proj.folder).as_posix()
        except ValueError:
            return str(path)

    def where(path: Path | None, proj: Project, doc=None) -> str:
        """Where Claude can read what the writer sees: the file itself, or for
        unsaved changes a copy of the editor's text."""
        if doc is None and path is not None:
            doc = app.docs.find_path(path)
        if doc is not None and (doc.path is None or doc.dirty):
            folder = snapshot_dir()
            folder.mkdir(parents=True, exist_ok=True)
            name = doc.path.name if doc.path is not None else re.sub(r"[^\w.-]+", "-", doc.title) + ".md"
            copy = folder / name
            copy.write_text(doc.text, encoding="utf-8")
            original = rel(doc.path, proj) if doc.path is not None else "not saved yet"
            return f"{copy} (a copy of {original} with the writer's unsaved changes)"
        return rel(path, proj)  # type: ignore[arg-type]

    def bible_path(proj: Project) -> Path:
        return proj.folder / str(table().get("story_bible") or "Story Bible.md")

    def bible_text(proj: Project) -> str:
        path = bible_path(proj)
        doc = app.docs.find_path(path)
        if doc is not None:
            return doc.text
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def header(proj: Project) -> str:
        """The note at the top of each Claude Code request that names the files."""
        lines = [f"Project folder: {proj.folder}"]
        if proj.binder is not None:
            lines.append(f"Binder (chapter order and research list): {where(proj.binder, proj)}")
        bible = bible_path(proj)
        if bible.exists() or app.docs.find_path(bible) is not None:
            lines.append(f"Story bible: {where(bible, proj)}")
        doc = app.active_document
        if doc is not None:
            lines.append(f"The writer is working on: {where(doc.path, proj, doc)}")
        return "\n".join(lines)

    def extra_dirs(proj: Project) -> tuple[Path, ...]:
        folders = [snapshot_dir()]
        doc = app.active_document
        if doc is not None and doc.path is not None:
            folders.append(doc.path.resolve().parent)
        if proj.binder is not None:
            binder = api.service("binder")
            for chapter in binder.chapters(proj.binder):
                folders.append(Path(chapter).resolve().parent)
            notes, _urls = binder.research(proj.binder)
            folders += [Path(n).resolve().parent for n in notes]
        out: list[Path] = []
        for folder in folders:
            try:
                folder.relative_to(proj.folder)
                continue  # inside the project folder already
            except ValueError:
                pass
            if folder not in out:
                out.append(folder)
        return tuple(out)

    # -- consent -------------------------------------------------------------------

    async def ready_to_send(p: client.Provider) -> bool:
        if p.kind == "cli" and claudecode.find(p.base_url) is None:
            app.notify(
                f"Cannot find the Claude Code program ({p.base_url or 'claude'}). Install Claude Code and log in, "
                "or set its path in AI > AI Settings. The AI Assistant's README explains how.",
                severity="error", timeout=12,
            )
            return False
        consented = list(table().get("consented", []))
        if p.host not in consented:
            if p.kind == "cli":
                where_to = (
                    "Claude, through the Claude Code program on this computer and your Claude plan "
                    f"(model: {p.model or 'your Claude Code default'})."
                )
                if files_on():
                    where_to += " Claude may also read files in the project's folder."
            else:
                local = p.host.startswith(("localhost", "127.0.0.1", "[::1]"))
                where_to = f"{'a server on this computer' if local else p.host} ({p.name}, model {p.model or 'not set'})."
            answer = await app.push_screen_wait(ConfirmDialog(
                "Send text to an AI?",
                textwrap.fill(f"AI commands send the text you choose to {where_to}", 70) + "\nNothing is sent otherwise. Allow this?",
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
        if p.kind == "cli":
            proj = project()
            if files_on():
                prompt = f"{header(proj)}\n\n{prompt}"
            else:
                bible = bible_text(proj).strip()
                prompt = (f"{context}\n\n" if context else "") + (f"The writer's story bible:\n\n{bible}\n\n" if bible else "") + prompt
            state["prompt"] = prompt
        else:
            bible = bible_text(project()).strip()
            state["conversation"] = [{"role": "user", "content": prompt}]
            state["context"] = "\n\n".join(part for part in (
                f"# Story bible (facts the writer has settled; follow it)\n\n{bible}" if bible else "", context) if part)
        await run(title, can_replace=can_replace, choices=choices, max_tokens=max_tokens)

    async def run(title: str, *, can_replace: bool, choices: bool, max_tokens: int | None = None) -> None:
        p = provider()
        panel = ReplyPanel(plugin, can_replace=can_replace, choices=choices)
        state["panel"] = panel
        hints = ["I insert"] + (["R replace"] if can_replace else []) + (["1-3 pick"] if choices else []) + [HINT_BASE]
        if p.kind == "cli":
            turn = sessions().turns(project().folder) + 1
            title = f"{title} (conversation turn {turn})"
        await api.show_panel(panel, f"AI: {title}", "  ".join(hints))
        cancel = threading.Event()
        state["cancel"] = cancel

        def on_text(piece: str) -> None:
            app.call_from_thread(panel.add, piece)

        try:
            if p.kind == "cli":
                reply = await run_cli(
                    state["prompt"], on_text, cancel=cancel,
                    on_tool=lambda line: app.call_from_thread(panel.note, line),
                    on_reset=lambda: app.call_from_thread(panel.reset),
                )
            else:
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
        panel.finish(text=reply)

    async def run_cli(prompt: str, on_text, *, cancel: threading.Event | None = None, on_tool=None, on_reset=None,
                      persist: bool = True, files: bool | None = None) -> str:
        """One Claude Code request, continuing the project's conversation unless ``persist`` is False."""
        p = provider()
        exe = claudecode.find(p.base_url)
        if exe is None:
            raise client.AIError(f"cannot find the Claude Code program ({p.base_url or 'claude'})")
        proj = project()
        store = sessions()
        files = files_on() if files is None else files
        session = store.get(proj.folder) if persist else None
        resume = session is not None
        if persist and session is None:
            session = claudecode.new_session_id()

        def go(session_id: str | None, resume: bool) -> claudecode.Reply:
            args = claudecode.build_args(
                exe, system=SYSTEM_FILES if files else SYSTEM, model=p.model, effort=str(table().get("effort") or ""),
                session=session_id, resume=resume, files=files, add_dirs=extra_dirs(proj) if files else (),
            )
            return claudecode.run(args, proj.folder, prompt, on_text, on_tool=on_tool, on_reset=on_reset, cancel=cancel)

        try:
            try:
                reply = await api.run_in_thread(go, session, resume)
            except claudecode.SessionMissing:
                store.forget(proj.folder)
                session = claudecode.new_session_id()
                app.notify("Claude Code no longer has the earlier conversation for this project; started a new one.")
                reply = await api.run_in_thread(go, session, False)
        except claudecode.ClaudeCodeError as exc:
            raise client.AIError(str(exc)) from exc
        if persist and reply.session_id:
            store.set(proj.folder, reply.session_id)
        return reply.text

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

        def add_to_bible(self, text: str) -> None:
            if not text:
                return
            path = bible_path(project())
            block = f"\n\n## From the AI Assistant, {datetime.date.today().isoformat()}\n\n{text}\n"
            doc = app.docs.find_path(path)
            if doc is not None:
                app.replace_document_text(doc, doc.text.rstrip() + block)
                app.status.flash(f"Added the reply to {path.name}. Save it to keep it.")
                return
            existing = path.read_text(encoding="utf-8") if path.exists() else BIBLE_TEMPLATE
            path.write_text(existing.rstrip() + block, encoding="utf-8")
            app.status.flash(f"Added the reply to {path.name}; AI > Story Bible opens it.")

        def follow_up(self) -> None:
            app.run_worker(follow_up_worker(), exit_on_error=False)

    plugin = Plugin()

    async def follow_up_worker() -> None:
        question = await app.push_screen_wait(InputDialog("Follow up", "Ask:", ""))
        if not question:
            return
        state["conversation"].append({"role": "user", "content": question})
        state["prompt"] = question
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

    def source(sel) -> str:
        """The text a command is about: the selection, or the whole document.
        With Claude Code reading files, the document is named rather than sent."""
        if sel:
            return f"The passage:\n\n{sel[3]}"
        if files_on() and app.active_document is not None:
            return "The text is the whole document the writer is working on (named above); read it."
        return f"The text:\n\n{document_text()}"

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
        await ask(f"{question}\n\n{source(sel)}", "Ask", can_replace=sel is not None)

    @api.command("ai.feedback", "&Feedback", menu="ai", enabled=has_doc,
                 description="A reader's notes on the selection, or the whole chapter")
    async def feedback(app):
        sel = selection()
        state["selection"] = None
        prompt = (
            "Give me feedback on this passage as an experienced editor would: what works, what does not, and the "
            "three changes that would help most. Consider clarity, pacing, voice, dialogue and structure, and quote "
            f"the lines you mean.\n\n{source(sel)}"
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
        await ask(f"Summarize this in a short paragraph, then list its key points.\n\n{source(sel)}", "Summary")

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
            if p.kind == "cli":
                # A one-off request, kept out of the project's conversation.
                reply = await run_cli(prompt, lambda _t: None, persist=False, files=False)
            else:
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

    CONTINUITY = (
        "List every continuity problem you find: characters' names, ages, looks and relationships; dates and the "
        "order of events; places and distances; objects; and facts that contradict the research notes or the "
        "story bible. For each, quote both passages and name the chapters. Group them by kind, most serious "
        "first. If you find none in a group, leave it out."
    )

    @api.command("ai.continuity", "&Continuity Check", menu="ai",
                 enabled=lambda a: a.active_document is not None and a.active_document.path is not None and api.service("binder") is not None,
                 description="Names, dates, places and facts that disagree across the whole binder")
    async def continuity(app):
        if files_on():
            await continuity_by_reading(app)
            return
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
        prompt = "Read the manuscript and research notes above. " + CONTINUITY
        await ask(prompt, f"Continuity: {title}", context=context, max_tokens=int(table().get("max_tokens_long", 4096)))

    async def continuity_by_reading(app):
        proj = project()
        binder = api.service("binder")
        if proj.binder is None:
            app.status.flash("Continuity Check works on a binder; this document is not in one.")
            return
        chapters = binder.chapters(proj.binder)
        notes, urls = binder.research(proj.binder)
        answer = await app.push_screen_wait(ConfirmDialog(
            "Continuity Check",
            f"Claude Code will read the {len(chapters)} chapters and {len(notes)} research notes of {proj.label} "
            "itself. This can take a few minutes on a long book. Go ahead?",
        ))
        if answer != "yes":
            return
        state["selection"] = None
        lines = ["Read every chapter of the binder, in this order:"]
        lines += [f"- {where(Path(c), proj)}" for c in chapters]
        if notes:
            lines.append("\nand these research notes:")
            lines += [f"- {where(Path(n), proj)}" for n in notes]
        if urls:
            lines.append("\nThe binder also lists these research links (do not fetch them): " + ", ".join(urls))
        await ask("\n".join(lines) + "\n\n" + CONTINUITY, f"Continuity: {proj.label}")

    @api.command("ai.bible", "Story &Bible", menu="ai", separator=True,
                 description="Open the project's story bible, which every AI request reads")
    async def open_bible(app):
        path = bible_path(project())
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(BIBLE_TEMPLATE, encoding="utf-8")
        await app.open_path(path)

    @api.command("ai.new_conversation", "&New Conversation", menu="ai", enabled=lambda a: is_cli(),
                 description="Claude Code: forget this project's conversation and start a fresh one")
    async def new_conversation(app):
        proj = project()
        if sessions().get(proj.folder) is None:
            app.status.flash("There is no conversation for this project yet.")
            return
        answer = await app.push_screen_wait(ConfirmDialog(
            "New Conversation",
            f"Start a fresh Claude Code conversation for {proj.label}? Claude forgets what was said so far; "
            "the story bible stays. (The old conversation stays in Claude Code, where claude --resume lists it.)",
        ))
        if answer == "yes":
            sessions().forget(proj.folder)
            app.status.flash("The next AI request starts a new conversation.")

    @api.command("ai.handoff", "C&ontinue in Claude Code...", menu="ai",
                 enabled=lambda a: is_cli() and sessions().get(project().folder) is not None,
                 description="The command that opens this project's conversation in Claude Code itself")
    async def handoff(app):
        proj = project()
        session = sessions().get(proj.folder)
        if session is None:
            return
        command = f'cd "{proj.folder}"\nclaude --resume {session}'
        app.copy_to_clipboard(command)
        await app.push_screen_wait(TextDialog(
            "Continue in Claude Code",
            Text(
                f"This project's conversation ({sessions().turns(proj.folder)} turns) is a normal Claude Code "
                "session. To carry on in a terminal, run (copied to the clipboard):\n\n"
                f"{command}\n\n"
                "Claude Code there has its usual tools and settings, unlike inside Inkmill. Anything you say "
                "there is part of the same conversation the next time you ask from Inkmill."
            ),
        ))

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
            "AI Provider",
            [(k, f"{v.name}  ({'the claude program' if v.kind == 'cli' else v.base_url})") for k, v in client.PRESETS.items()],
            current.id,
        ))
        if not choice:
            return
        preset = client.PRESETS[choice]
        same = choice == current.id
        if preset.kind == "cli":
            await claude_code_settings(app, current if same else preset)
            return
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

    async def claude_code_settings(app, current: client.Provider):
        model = await app.push_screen_wait(InputDialog(
            "Model", "sonnet, opus, haiku or a full model name; empty uses your Claude Code default:", current.model))
        if model is None:
            return
        command = await app.push_screen_wait(InputDialog(
            "Claude Code program", "The command that runs Claude Code:", current.base_url or "claude"))
        if command is None:
            return
        files = await app.push_screen_wait(ChoiceDialog(
            "Project files",
            [("yes", "Claude may read the project's files (recommended)"),
             ("no", "Send only the text each command names")],
            "yes" if table().get("file_access", True) else "no",
        ))
        if files is None:
            return
        table()["provider"] = "claude-code"
        table()["model"] = model.strip()
        table()["file_access"] = files == "yes"
        if command.strip() and command.strip() != "claude":
            table()["command"] = command.strip()
        else:
            table().pop("command", None)
        api.save_settings()
        found = claudecode.find(command.strip())
        if found is None:
            app.notify(f"Saved, but '{command.strip() or 'claude'}' was not found. See the AI Assistant README.", severity="warning")
        else:
            app.status.flash(f"AI: Claude Code ({found[0]}), {model.strip() or 'default model'}")
