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

Every request and reply is also kept in the project folder
(.inkmill/ai-conversation.jsonl), whichever provider answered, so the
history outlives Claude Code's clean-up of old conversations.
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
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.containers import Horizontal
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from inkmill import frontmatter
from inkmill.config import config_dir, state_dir
from inkmill.screens.dialogs import ChoiceDialog, ConfirmDialog, Dialog, InputDialog, TextDialog

from . import bible, claudecode, client, conversation
from .conversation import CONTINUITY, FEEDBACK, PASSAGE, REWRITE, SUMMARY, TEXT, WHOLE_DOCUMENT

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
SPLIT = re.compile(r"^\s*-{3,}\s*$", re.MULTILINE)


REQUEST_LINES = 8


class ReplyPanel(Vertical):
    """A reply with the request it answers, keys to use it, and the earlier
    turns of the conversation to page through.

    ``history`` is the conversation so far; ``live`` is the request being
    sent now, whose reply streams in. Without ``live`` the panel only shows
    earlier turns, starting at ``index``.
    """

    DEFAULT_CSS = """
    ReplyPanel { height: 1fr; }
    ReplyPanel > VerticalScroll { height: 1fr; padding: 0 1; }
    ReplyPanel #ai-request { color: $im-dialog-fg 70%; height: auto; margin-bottom: 1; }
    ReplyPanel #ai-note { color: $im-dialog-fg 70%; text-style: italic; height: auto; }
    """

    can_focus = True

    def __init__(self, plugin, *, can_replace: bool = False, choices: bool = False,
                 history: list | None = None, live=None, index: int | None = None) -> None:
        super().__init__()
        self.plugin = plugin
        self.can_replace = can_replace
        self.choices = choices
        self.entries = list(history or []) + ([live] if live is not None else [])
        self.live = len(self.entries) - 1 if live is not None else None
        self.index = index if index is not None else len(self.entries) - 1
        self.done = live is None
        self.live_note = ""
        self.error: str | None = None

    # -- what is shown -----------------------------------------------------------

    @property
    def viewing_live(self) -> bool:
        return self.live is not None and self.index == self.live

    @property
    def text(self) -> str:
        """The reply on screen."""
        return self.entries[self.index].reply if self.entries else ""

    def compose(self):
        with VerticalScroll():
            yield Static("", id="ai-request")
            yield Static("", id="ai-note")
            yield Static("", id="ai-reply")

    def on_mount(self) -> None:
        self.show_entry()

    def heading(self) -> str:
        entry = self.entries[self.index]
        return f"AI: {entry.label or 'Claude Code'} (turn {self.index + 1} of {len(self.entries)})"

    def hint(self) -> str:
        keys = []
        if self.done or not self.viewing_live:
            keys.append("I insert")
            if self.viewing_live and self.can_replace:
                keys.append("R replace")
            if self.viewing_live and self.choices:
                keys.append("1-3 pick")
        if self.done:
            keys.append("Q follow up")
        keys += ["<- -> turns", "L list"]
        if self.done or not self.viewing_live:
            keys += ["B bible", "C copy"]
        return "  ".join(keys + ["Esc close"])

    def show_entry(self) -> None:
        if not self.entries:
            return
        entry = self.entries[self.index]
        request = self.query_one("#ai-request", Static)
        if entry.label or entry.request:
            head = "Me" + (f": {entry.label}" if entry.label else "") + (f"  ({entry.about})" if entry.about else "")
            body = entry.request.strip().splitlines()
            if len(body) > REQUEST_LINES:
                body = body[:REQUEST_LINES] + [f"(+{len(body) - REQUEST_LINES} more lines)"]
            shown = Text(head, style="bold")
            if body:
                shown.append("\n" + "\n".join(body))
            request.update(shown)
            request.display = True
        else:
            request.display = False
        if self.viewing_live and not self.done:
            self.query_one("#ai-note", Static).update(self.live_note)
        else:
            self.query_one("#ai-note", Static).update(
                "Looked at: " + ", ".join(entry.looked_at) if entry.looked_at else "")
        reply = self.query_one("#ai-reply", Static)
        if self.viewing_live and not self.done:
            reply.update(Text(entry.reply) if entry.reply else Text("Waiting for the reply...", style="italic"))
        elif self.viewing_live and self.error:
            reply.update(Text(f"{entry.reply}\n\n{self.error}" if entry.reply else self.error, style="bold"))
        else:
            reply.update(Markdown(entry.reply) if entry.reply.strip() else Text("(no reply)", style="italic"))
        self.query_one(VerticalScroll).scroll_home(animate=False)
        self.plugin.panel_changed(self)

    def go(self, index: int) -> None:
        if self.entries and 0 <= index < len(self.entries) and index != self.index:
            self.index = index
            self.show_entry()

    # -- the live reply --------------------------------------------------------

    def add(self, piece: str) -> None:
        entry = self.entries[self.live]
        entry.reply += piece
        if self.viewing_live:
            self.query_one("#ai-reply", Static).update(Text(entry.reply))
            self.query_one(VerticalScroll).scroll_end(animate=False)

    def note(self, line: str) -> None:
        """What Claude is doing between pieces of text (reading a chapter)."""
        self.live_note = line
        if self.viewing_live:
            self.query_one("#ai-note", Static).update(line)

    def reset(self) -> None:
        self.entries[self.live].reply = ""
        if self.viewing_live:
            self.query_one("#ai-reply", Static).update(Text("Writing the reply...", style="italic"))

    def finish(self, error: str | None = None, text: str | None = None) -> None:
        self.done = True
        self.live_note = ""
        self.error = error
        if text is not None:
            self.entries[self.live].reply = text
        if self.viewing_live:
            self.show_entry()
            if not error:
                self.query_one(VerticalScroll).scroll_home(animate=False)
        else:
            self.plugin.panel_changed(self)

    def alternatives(self) -> list[str]:
        return [part.strip() for part in SPLIT.split(self.text) if part.strip()]

    # -- keys ------------------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        key = (event.character or "").lower()
        if event.key in ("left", "right") or key in ("[", "]"):
            self.go(self.index + (-1 if event.key == "left" or key == "[" else 1))
            event.stop()
            return
        if key == "l":
            self.plugin.pick_turn(self)
            event.stop()
            return
        ready = self.done or not self.viewing_live
        if not ready or not key:
            return
        handled = True
        if key == "i":
            self.plugin.insert(self.text.strip())
        elif key == "r" and self.can_replace and self.viewing_live:
            self.plugin.replace(self.text.strip())
        elif key in "123" and self.choices and self.viewing_live:
            options = self.alternatives()
            index = int(key) - 1
            if index < len(options):
                self.plugin.replace(_strip_number(options[index]))
        elif key == "c":
            self.app.copy_to_clipboard(self.text)
            self.app.status.flash("Copied the reply.")
        elif key == "b":
            self.plugin.add_to_bible(self.text.strip())
        elif key == "q" and self.done:
            self.plugin.follow_up()
        else:
            handled = False
        if handled:
            event.stop()


class TurnList(Dialog):
    """The turns of a conversation, to pick one; typing filters them."""

    DEFAULT_CSS = Dialog.DEFAULT_CSS + """
    TurnList .im-dialog { width: 96; }
    TurnList OptionList { height: auto; max-height: 20; background: $im-dialog-bg; border: none; }
    """

    def __init__(self, title: str, entries: list, current: int | None = None) -> None:
        super().__init__()
        self.title_text = title
        self.rows = [
            (i, f"{i + 1:>3}  {(e.label or 'Claude Code')[:16]:<16} {(e.about or '')[:16]:<16} {conversation.describe(e)}")
            for i, e in enumerate(entries)
        ]
        self.search = {i: f"{row}\n{entries[i].request}\n{entries[i].reply}".lower() for i, row in self.rows}
        self.current = len(entries) - 1 if current is None else current

    def compose(self):
        with Vertical(classes="im-dialog"):
            yield Label(self.title_text, classes="im-title")
            yield Input(placeholder="Type to search the turns; Enter shows one", id="filter")
            yield OptionList()

    def on_mount(self) -> None:
        self.fill("")
        self.query_one(Input).focus()

    def fill(self, text: str) -> None:
        words = text.lower().split()
        shown = [(i, row) for i, row in self.rows if all(w in self.search[i] for w in words)]
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([Option(Text(row, no_wrap=True, overflow="ellipsis"), id=str(i)) for i, row in shown])
        ids = [i for i, _ in shown]
        if ids:
            options.highlighted = ids.index(self.current) if self.current in ids else len(ids) - 1

    def on_input_changed(self, event: Input.Changed) -> None:
        self.fill(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        options = self.query_one(OptionList)
        if options.highlighted is not None and options.option_count:
            self.dismiss(int(options.get_option_at_index(options.highlighted).id))

    def on_key(self, event: events.Key) -> None:
        options = self.query_one(OptionList)
        if self.query_one(Input).has_focus and event.key in ("up", "down", "pageup", "pagedown") and options.option_count:
            step = {"up": -1, "down": 1, "pageup": -10, "pagedown": 10}[event.key]
            current = options.highlighted if options.highlighted is not None else 0
            options.highlighted = max(0, min(options.option_count - 1, current + step))
            event.stop()

    def on_option_list_option_selected(self, event) -> None:
        self.dismiss(int(event.option.id))


class BibleReview(Dialog):
    """Suggested story bible entries, each checked; the writer unchecks what
    is wrong and adds the rest. Dismisses with the indexes to add, or None."""

    DEFAULT_CSS = Dialog.DEFAULT_CSS + """
    BibleReview .im-dialog { width: 100; max-height: 90%; }
    BibleReview OptionList { height: auto; max-height: 24; background: $im-dialog-bg; border: none; }
    BibleReview #hint { color: $im-dialog-fg 70%; }
    """

    BINDINGS = [*Dialog.BINDINGS, Binding("space", "toggle_current", show=False),
                Binding("a", "add", show=False)]

    def __init__(self, title: str, proposals: list) -> None:
        super().__init__()
        self.title_text = title
        self.proposals = proposals
        self.checked = set(range(len(proposals)))

    def row(self, i: int) -> Text:
        p = self.proposals[i]
        shown = Text("[x] " if i in self.checked else "[ ] ")
        shown.append(f"{p.section}: ", style="bold")
        shown.append(p.entry)
        if p.note:
            shown.append(f" (changes the bible: {p.note})", style="italic")
        return shown

    def compose(self):
        with Vertical(classes="im-dialog"):
            yield Label(self.title_text, classes="im-title")
            yield OptionList(*[Option(self.row(i), id=str(i)) for i in range(len(self.proposals))])
            yield Label("Space or Enter checks and unchecks. A adds the checked entries, Esc cancels.", id="hint")
            with Horizontal(classes="im-buttons"):
                yield Button("Add checked", id="add", compact=True)
                yield Button("Cancel", id="cancel", compact=True)

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        options.focus()
        if options.option_count:
            options.highlighted = 0

    def toggle(self, i: int) -> None:
        self.checked ^= {i}
        self.query_one(OptionList).replace_option_prompt_at_index(i, self.row(i))

    def chosen(self) -> list[int]:
        return sorted(self.checked)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.toggle(int(event.option.id))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.chosen() if event.button.id == "add" else None)

    # Bindings, not on_key, so they run after a queued move of the highlight.
    def action_toggle_current(self) -> None:
        options = self.query_one(OptionList)
        if options.has_focus and options.highlighted is not None:
            self.toggle(options.highlighted)

    def action_add(self) -> None:
        self.dismiss(self.chosen())


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

    def keep() -> bool:
        """Whether turns are kept in the project folder's log."""
        return bool(table().get("keep_history", True))

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
            lines.append(f"{conversation.WORKING_ON}{where(doc.path, proj, doc)}")
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
                prompt = (f"{context}\n\n" if context else "") + (f"{conversation.BIBLE}{bible}\n\n" if bible else "") + prompt
            state["prompt"] = prompt
        else:
            bible = bible_text(project()).strip()
            state["conversation"] = [{"role": "user", "content": prompt}]
            state["context"] = "\n\n".join(part for part in (
                f"# Story bible (facts the writer has settled; follow it)\n\n{bible}" if bible else "", context) if part)
        await run(title, can_replace=can_replace, choices=choices, max_tokens=max_tokens)

    def live_exchange(title: str, request: str) -> conversation.Exchange:
        """The request being sent, as the reply panel shows it."""
        if title == "Follow-up":
            return conversation.Exchange(title, request)
        doc = app.active_document
        about = conversation.request_file(request) or (doc.path.name if doc is not None and doc.path is not None else "")
        return conversation.Exchange(title, conversation.clean_request(request, from_inkmill=True)[1], about=about)

    async def run(title: str, *, can_replace: bool, choices: bool, max_tokens: int | None = None) -> None:
        p = provider()
        request = state["prompt"] if p.kind == "cli" else state["conversation"][-1]["content"]
        live = live_exchange(title, request)
        past = await history()
        panel = ReplyPanel(plugin, can_replace=can_replace, choices=choices, history=past, live=live)
        state["panel"] = panel
        await api.show_panel(panel, panel.heading(), panel.hint())
        cancel = threading.Event()
        state["cancel"] = cancel

        def on_text(piece: str) -> None:
            app.call_from_thread(panel.add, piece)

        tools: list[dict] = []
        try:
            if p.kind == "cli":
                answer = await run_cli(
                    state["prompt"], on_text, cancel=cancel,
                    on_tool=lambda line: app.call_from_thread(panel.note, line),
                    on_reset=lambda: app.call_from_thread(panel.reset),
                )
                reply, tools = answer.text, answer.tools
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
        live.reply = reply
        live.looked_at = [conversation.looked_at(t) for t in tools]
        live.time = conversation.stamp()
        await record(live, p)
        panel.finish(text=reply)

    async def record(exchange: conversation.Exchange, p: client.Provider) -> None:
        """Keep a finished turn: in the project's log, or for the providers
        with no other record, in memory until Inkmill quits."""
        proj = project()
        if not keep():
            if p.kind != "cli":
                memory(proj.folder).append(exchange)
            return
        session = (sessions().get(proj.folder) or "") if p.kind == "cli" else ""
        try:
            await api.run_in_thread(conversation.Log(proj.folder).append, exchange, session=session, provider=p.id)
        except OSError as exc:
            memory(proj.folder).append(exchange)
            app.notify(f"Could not keep this turn in {conversation.LOG_FOLDER}/{conversation.LOG_NAME}: {exc}",
                       severity="warning")

    # -- the conversation so far -------------------------------------------------

    def memory(folder: Path) -> list:
        """This run's exchanges for a project when the log is turned off (or
        cannot be written). Lost when Inkmill quits."""
        return state.setdefault("memory", {}).setdefault(folder.resolve().as_posix(), [])

    async def history() -> list:
        """The project's earlier exchanges, oldest first.

        With the log on (the default), turns Claude Code has that the log
        lacks are copied into it first, so turns asked before the log existed,
        or typed in Claude Code itself, are kept too.
        """
        proj = project()
        log = conversation.Log(proj.folder) if keep() else None
        extra = list(memory(proj.folder))
        if is_cli():
            session = sessions().get(proj.folder)
            source = conversation.find(session) if session else None
            found: list = []
            if source is not None:
                try:
                    found = conversation.exchanges(await api.run_in_thread(conversation.load, source))
                except OSError:
                    found = []
            if log is None:
                return found
            if found:
                try:
                    await api.run_in_thread(log.sync, session, found)
                except OSError:
                    return found
        elif log is None:
            return extra
        try:
            return await api.run_in_thread(log.exchanges) + extra
        except OSError:
            return extra

    def seed(proj: Project, files: bool) -> str:
        """For the first request of a new Claude Code conversation: the turns
        the log holds since the writer last started afresh, which Claude Code
        no longer has (it cleaned them up, or the folder came from elsewhere)."""
        if not keep():
            return ""
        try:
            earlier = conversation.Log(proj.folder).exchanges(since_reset=True)
        except OSError:
            return ""
        if not earlier:
            return ""
        turns = conversation.exchanges_to_turns(earlier)
        if files:
            path = proj.folder / conversation.LOG_FOLDER / conversation.EARLIER_NAME
            try:
                path.write_text(conversation.to_markdown(turns, f"Earlier conversation about {proj.label}"), encoding="utf-8")
            except OSError:
                return ""
            body = (f"This is a new conversation. The earlier one ({len(earlier)} turns) is saved in {path}; "
                    "read it when a request depends on what was said before.")
        else:
            text = conversation.to_markdown(turns, "Earlier conversation")
            limit = int(table().get("max_context_chars", 600_000)) // 4
            if len(text) > limit:
                text = "(The oldest turns are left out.)\n\n" + text[-limit:]
            body = "This is a new conversation. The earlier one was:\n\n" + text
        return f"{conversation.SEED_START}{body}\n{conversation.SEED_END}\n\n"

    async def run_cli(prompt: str, on_text, *, cancel: threading.Event | None = None, on_tool=None, on_reset=None,
                      persist: bool = True, files: bool | None = None) -> claudecode.Reply:
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
            text = prompt if resume or not persist else seed(proj, files) + prompt
            return claudecode.run(args, proj.folder, text, on_text, on_tool=on_tool, on_reset=on_reset, cancel=cancel)

        try:
            try:
                reply = await api.run_in_thread(go, session, resume)
            except claudecode.SessionMissing:
                store.forget(proj.folder)
                session = claudecode.new_session_id()
                kept = keep() and conversation.Log(proj.folder).exchanges(since_reset=True)
                app.notify("Claude Code no longer has the earlier conversation for this project; started a new one"
                           + (" and gave it the turns Inkmill kept." if kept else "."))
                reply = await api.run_in_thread(go, session, False)
        except claudecode.ClaudeCodeError as exc:
            raise client.AIError(str(exc)) from exc
        if persist and reply.session_id:
            store.set(proj.folder, reply.session_id)
        return reply

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

        def panel_changed(self, panel: ReplyPanel) -> None:
            if api.owns_panel and app.panel.content is panel:
                app.panel.set_title(panel.heading())
                app.panel.set_hint(panel.hint())

        def pick_turn(self, panel: ReplyPanel) -> None:
            async def pick() -> None:
                index = await app.push_screen_wait(TurnList(f"Conversation: {project().label}", panel.entries, panel.index))
                if index is not None:
                    panel.go(index)
            app.run_worker(pick(), exit_on_error=False)

    plugin = Plugin()

    async def follow_up_worker() -> None:
        question = await app.push_screen_wait(InputDialog("Follow up", "Ask:", ""))
        if not question:
            return
        state["conversation"].append({"role": "user", "content": question})
        state["prompt"] = question
        await run("Follow-up", can_replace=state["selection"] is not None, choices=False)

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
            return f"{PASSAGE}{sel[3]}"
        if files_on() and app.active_document is not None:
            return WHOLE_DOCUMENT
        return f"{TEXT}{document_text()}"

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
        await ask(f"{FEEDBACK}\n\n{source(sel)}", "Feedback")

    @api.command("ai.rewrite", "&Rewrite Selection...", menu="ai", enabled=lambda a: selection() is not None,
                 description="Three alternatives for the selection; pick one with 1, 2 or 3")
    async def rewrite(app):
        sel = selection()
        state["selection"] = sel
        how = await app.push_screen_wait(InputDialog("Rewrite", "How? (tighter, warmer, more formal, simpler...)", "tighter"))
        if not how:
            return
        prompt = f"{REWRITE.format(how=how)}\n\n{sel[3]}"
        await ask(prompt, f"Rewrite ({how})", can_replace=True, choices=True)

    @api.command("ai.summarize", "Su&mmarize", menu="ai", enabled=has_doc)
    async def summarize(app):
        sel = selection()
        state["selection"] = None
        await ask(f"{SUMMARY}\n\n{source(sel)}", "Summarize")

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
                reply = (await run_cli(prompt, lambda _t: None, persist=False, files=False)).text
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

    @api.command("ai.bible_update", "&Update Story Bible from Conversation...", menu="ai", enabled=has_doc,
                 description="Suggest bible entries for what the conversation settled; you pick which to add")
    async def update_bible(app):
        p = provider()
        proj = project()
        past = await history()
        if not past:
            app.status.flash("There is no conversation for this project yet.")
            return
        if not await ready_to_send(p):
            return
        path = bible_path(proj)
        current = bible_text(proj) or BIBLE_TEMPLATE
        headings = bible.sections(current)
        talk = conversation.to_markdown(conversation.exchanges_to_turns(past), f"Conversation about {proj.label}")
        reading = p.kind == "cli" and files_on()
        if reading:
            # Claude Code reads both files itself, so a long conversation is not squeezed into the request.
            saved = proj.folder / conversation.LOG_FOLDER / "conversation-for-bible.md"
            try:
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_text(talk, encoding="utf-8")
            except OSError as exc:
                app.notify(f"Could not write {saved}: {exc}", severity="error")
                return
            where_bible = f" ({where(path, proj)})" if path.exists() or app.docs.find_path(path) else " (none yet)"
            prompt = bible.request(f"The file {saved} holds the writer's conversation with you about their story; read all of it.",
                                   where_bible, headings)
        else:
            limit = int(table().get("max_context_chars", 600_000)) // 2
            if len(talk) > limit:
                talk = "(The oldest turns are left out.)\n\n" + talk[-limit:]
            prompt = bible.request(f"Here is the writer's conversation with you about their story:\n\n{talk}\n\n",
                                   f", below,", headings) + f"\n\nThe story bible:\n\n{current}"
        app.status.flash(f"Reading {len(past)} turns for the story bible; this can take a minute...", seconds=180)
        try:
            if p.kind == "cli":
                # A one-off request, kept out of the project's conversation.
                reply = (await run_cli(prompt, lambda _t: None, persist=False, files=reading)).text
            else:
                reply = await api.run_in_thread(
                    client.stream, p, client.load_key(config_dir(), p), SYSTEM, [{"role": "user", "content": prompt}],
                    lambda _t: None, max_tokens=int(table().get("max_tokens_long", 4096)))
        except client.AIError as exc:
            app.status.clear_flash()
            app.notify(f"Story bible update failed: {exc}", severity="error")
            return
        app.status.clear_flash()
        found = bible.parse(reply)
        if found is None:
            app.notify("The reply was not a list of entries; it is shown in the panel, where B adds it as it is.",
                       severity="warning", timeout=10)
            panel = ReplyPanel(plugin, history=[conversation.Exchange("Story bible", "", reply)])
            state["panel"] = panel
            await api.show_panel(panel, panel.heading(), panel.hint())
            return
        if not found:
            app.status.flash("Nothing new for the story bible.")
            return
        picked = await app.push_screen_wait(BibleReview(f"Add to {path.name}? ({len(found)} suggested)", found))
        if not picked:
            return
        accepted = [found[i] for i in picked]
        updated = bible.merge(current, accepted)
        doc = app.docs.find_path(path)
        if doc is not None:
            app.replace_document_text(doc, updated)
            app.status.flash(f"Added {len(accepted)} entries to {path.name}. Save it to keep them; Ctrl+Z undoes.")
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(updated, encoding="utf-8")
        except OSError as exc:
            app.notify(f"Could not write {path}: {exc}", severity="error")
            return
        app.status.flash(f"Added {len(accepted)} entries to {path.name}; AI > Story Bible opens it.")

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
            "the story bible stays, and Conversation History still lists the earlier turns.",
        ))
        if answer == "yes":
            await history()  # keep Claude Code's turns in the log before letting go of them
            sessions().forget(proj.folder)
            if keep():
                try:
                    conversation.Log(proj.folder).reset()
                except OSError:
                    pass
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

    @api.command("ai.history", "Conversation &History...", menu="ai",
                 description="Earlier requests and replies in this project's conversation")
    async def show_history(app):
        past = await history()
        if not past:
            app.status.flash("There is no conversation for this project yet.")
            return
        await browse(f"Conversation: {project().label}", past)

    async def browse(title: str, past: list) -> None:
        index = await app.push_screen_wait(TurnList(title, past))
        if index is None:
            return
        panel = ReplyPanel(plugin, history=past, index=index)
        state["panel"] = panel
        await api.show_panel(panel, panel.heading(), panel.hint())

    def on_saved_note(a) -> bool:
        doc = a.active_document
        return doc is not None and conversation.is_saved_conversation(doc.text)

    @api.command("ai.show_saved", "Sho&w Saved Conversation...", menu="ai", enabled=on_saved_note,
                 description="Page through the turns of the saved conversation note you are reading")
    async def show_saved(app):
        doc = app.active_document
        past = conversation.from_markdown(doc.text)
        if not past:
            app.status.flash("This note has no conversation turns in it.")
            return
        await browse(f"Saved conversation: {doc.title}", past)

    @api.command("ai.save_conversation", "Sa&ve Conversation as Research Note...", menu="ai",
                 enabled=lambda a: is_cli() and sessions().get(project().folder) is not None,
                 description="Claude Code: write this project's conversation into a research note")
    async def save_conversation(app):
        proj = project()
        session = sessions().get(proj.folder)
        if session is None:
            app.status.flash("There is no conversation for this project yet.")
            return
        source = conversation.find(session)
        if source is None:
            app.notify(
                f"Claude Code's copy of this conversation ({session}) is not under "
                f"{conversation.claude_home() / 'projects'}. It may have been deleted, or Claude Code keeps "
                "its files elsewhere (set CLAUDE_CONFIG_DIR before starting Inkmill).",
                severity="warning", timeout=10,
            )
            return
        try:
            exchange = await api.run_in_thread(conversation.turns, source)
        except OSError as exc:
            app.notify(f"Could not read the conversation: {exc}", severity="error")
            return
        if not exchange:
            app.status.flash("The conversation has nothing in it yet.")
            return
        today = datetime.date.today().isoformat()
        title = await app.push_screen_wait(InputDialog(
            "Save Conversation as Research Note", "Title:", f"AI conversation {today}"))
        if not title or not title.strip():
            return
        title = title.strip()
        asked = sum(1 for t in exchange if t.role == "me")
        intro = (f"A conversation with Claude about {proj.label}, {asked} request(s), saved {today}. "
                 "Requests made from Inkmill are shown without the note naming the project's files.")
        body = conversation.to_markdown(exchange, title, intro)
        fields = {"source": f"claude-code session {session}", "saved": today}
        binder = api.service("binder")
        doc = app.active_document
        if binder is not None and hasattr(binder, "add_research_note") and doc is not None and doc.path is not None:
            target = binder.add_research_note(doc.path, title, body, fields)
        else:
            folder = proj.folder / "research"
            folder.mkdir(parents=True, exist_ok=True)
            stem = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "ai-conversation"
            target = folder / f"{stem}.md"
            n = 2
            while target.exists():
                target = folder / f"{stem}-{n}.md"
                n += 1
            head = f'---\ntitle: "{title.replace(chr(34), chr(39))}"\ntype: research\n'
            head += "".join(f"{k}: {v}\n" for k, v in fields.items()) + "---\n"
            target.write_text(head + body, encoding="utf-8")
        await app.open_path(target)
        app.status.flash(f"Saved {asked} request(s) and their replies to {target.name}.")

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


def import_conversation(folder: Path, source: str = "") -> list[str]:
    """``inkmill --import-conversation FOLDER [--from SOURCE]``: copy earlier
    turns into the project folder's log, and say what was copied.

    SOURCE is empty (the Claude Code conversation Inkmill uses for FOLDER, or
    if none, every Claude Code conversation started in FOLDER), ``all``, a
    Claude Code session id, a Claude Code ``.jsonl`` file, or a conversation
    note saved with AI > Save Conversation as Research Note. Copying twice
    adds nothing the second time.
    """
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"{folder}: no such folder")
    log = conversation.Log(folder)
    lines: list[str] = []
    candidate = Path(source).expanduser() if source else None
    if candidate is not None and candidate.is_file() and candidate.suffix.lower() == ".md":
        text = candidate.read_text(encoding="utf-8", errors="replace")
        found = conversation.from_markdown(text)
        if not found:
            raise ValueError(f"{candidate}: no conversation turns in it (was it saved by the AI Assistant?)")
        saved = frontmatter.read(text).get("saved") if text.startswith("---") else None
        when = conversation.stamp(str(saved)) if saved else conversation.stamp(
            datetime.datetime.fromtimestamp(candidate.stat().st_mtime, datetime.timezone.utc))
        for e in found:
            e.time = e.time or when
        added = log.add_missing(found, source=f"note {candidate.name}")
        lines.append(f"{candidate.name}: {added} of {len(found)} turn(s) added")
        return lines + [f"Kept in {log.path}"]
    if candidate is not None and candidate.is_file() and candidate.suffix.lower() == ".jsonl":
        files = [candidate]
    elif source == "all":
        files = conversation.transcripts_for(folder)
    elif source:
        path = conversation.find(source)
        if path is None:
            raise ValueError(f"no Claude Code conversation {source} under {conversation.claude_home() / 'projects'}")
        files = [path]
    else:
        session = claudecode.Sessions(state_dir() / "ai" / "claude-code-sessions.json").get(folder)
        path = conversation.find(session) if session else None
        files = [path] if path is not None else conversation.transcripts_for(folder)
    if not files:
        raise ValueError(f"no Claude Code conversation found for {folder}")
    for path in files:
        found = conversation.exchanges(conversation.turns(path))
        added = log.sync(path.stem, found)
        lines.append(f"Claude Code conversation {path.stem}: {added} of {len(found)} turn(s) added")
    return lines + [f"Kept in {log.path}"]
