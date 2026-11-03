"""Spelling & Thesaurus.

* Check Spelling (Ctrl+F2) walks through each unknown word, WordPerfect
  style: pick a suggestion, type a fix, skip, skip all, or add it to your
  dictionary.
* Words not in the dictionary are underlined as you write (View setting
  ``underline``).
* Thesaurus (Alt+F1) offers synonyms for the word under the cursor. It looks
  them up online at datamuse.com, so it needs a network connection.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from rich.style import Style

from inkmill.config import config_dir
from inkmill.screens.dialogs import ChoiceDialog

from .checker import WORD, Checker, match_case
from .dialog import SpellDialog

OWNER = "spelling"
THESAURUS_URL = "https://api.datamuse.com/words?"


def dictionaries_dir():
    return config_dir() / "dictionaries"


def register(api):
    app = api.app
    state: dict = {"checker": None}

    def checker() -> Checker:
        if state["checker"] is None:
            state["checker"] = Checker([dictionaries_dir()], dictionaries_dir() / "personal.txt")
        return state["checker"]

    def has_doc(_app) -> bool:
        return app.active_editor is not None

    api.add_menu("tools", "&Tools")
    api.decoration_style("spelling.error", lambda v: Style(underline=True, color=v.get("im-mark")))

    # -- underline as you type ----------------------------------------------

    def underline_enabled() -> bool:
        return bool(api.settings.get("underline", True))

    async def refresh_underlines(doc=None) -> None:
        editor = app.active_editor
        if editor is None or (doc is not None and editor.doc is not doc):
            return
        if not underline_enabled() or not editor.doc.format.markdown and editor.doc.format.id != "text":
            editor.clear_decorations(OWNER)
            return
        text = editor.text
        errors = await api.run_in_thread(lambda: checker().errors(text))
        if editor.text != text:
            return  # typed meanwhile; the next change event redoes it
        ranges = [(editor.location_of(a), editor.location_of(b), "spelling.error") for a, b, _ in errors]
        editor.set_decorations(OWNER, ranges)

    @api.on("document_changed")
    async def changed(app, doc):
        await refresh_underlines(doc)

    @api.on("document_activated")
    async def activated(app, doc):
        await refresh_underlines(doc)

    @api.on("ready")
    async def ready(app):
        await refresh_underlines()

    @api.command("spelling.underline", "&Underline Misspellings", menu="tools", separator=False,
                 description="Turn the as-you-type underline on or off")
    async def toggle_underline(app):
        api.settings["underline"] = not underline_enabled()
        api.save_settings()
        await refresh_underlines()
        app.status.flash("Spelling underline " + ("on." if underline_enabled() else "off."))

    # -- check spelling --------------------------------------------------------

    @api.command("spelling.check", "Check &Spelling...", "ctrl+f2", menu="tools", enabled=has_doc,
                 description="Go through each word not in the dictionary")
    async def check(app):
        editor = app.active_editor
        sel = editor.selection
        start = min(editor.index_of(sel.start), editor.index_of(sel.end))
        end = max(editor.index_of(sel.start), editor.index_of(sel.end))
        scope_end = end if end > start else None
        position = start if end > start else 0
        fixed = 0
        while True:
            text = editor.text
            limit = scope_end if scope_end is not None else len(text)
            errors = [e for e in checker().errors(text) if e[0] >= position and e[1] <= limit]
            if not errors:
                break
            a, b, word = errors[0]
            editor.select_range(editor.location_of(a), editor.location_of(b))
            line_start = text.rfind("\n", 0, a) + 1
            line_end = text.find("\n", b)
            line_end = len(text) if line_end == -1 else line_end
            left = max(line_start, a - 30)
            right = min(line_end, b + 40)
            context = ("..." if left > line_start else "") + text[left:right] + ("..." if right < line_end else "")
            offset = a - left + (3 if left > line_start else 0)
            suggestions = await api.run_in_thread(checker().suggest, word)
            answer = await app.push_screen_wait(
                SpellDialog(word, context, offset, suggestions, f"({len(errors)} left)")
            )
            if answer.action == "stop":
                break
            if answer.action == "replace" and answer.text:
                editor.replace(answer.text, editor.location_of(a), editor.location_of(b))
                delta = len(answer.text) - (b - a)
                if scope_end is not None:
                    scope_end += delta
                position = a + len(answer.text)
                fixed += 1
            elif answer.action == "ignore":
                checker().ignored.add(word)
                position = a
            elif answer.action == "add":
                checker().add_to_personal(word)
                position = a
            else:
                position = b
        editor.focus()
        await refresh_underlines()
        app.status.flash(f"Spelling done. {fixed} correction(s)." if fixed else "Spelling done.")

    @api.command("spelling.add_word", "Add &Word to Dictionary", menu="tools", enabled=has_doc)
    async def add_word(app):
        word = word_at_cursor(app.active_editor)
        if word is None:
            app.status.flash("Put the cursor on a word first.")
            return
        checker().add_to_personal(word[2])
        await refresh_underlines()
        app.status.flash(f"Added {word[2]!r} to your dictionary.")

    @api.command("spelling.personal", "Edit Personal &Dictionary", menu="tools")
    async def personal(app):
        path = dictionaries_dir() / "personal.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# One word per line. Save to apply.\n", encoding="utf-8")
        await app.open_path(path)

    @api.on("document_saved")
    async def dictionary_saved(app, doc):
        if doc.path is not None and doc.path.parent.resolve() == dictionaries_dir().resolve():
            state["checker"] = None
            app.status.flash("Dictionary reloaded.")

    # -- thesaurus ---------------------------------------------------------------

    @api.command("spelling.thesaurus", "&Thesaurus...", "alt+f1", menu="tools", enabled=has_doc,
                 description="Synonyms for the word under the cursor (online)")
    async def thesaurus(app):
        editor = app.active_editor
        found = word_at_cursor(editor)
        if found is None:
            app.status.flash("Put the cursor on a word first.")
            return
        start, end, word = found
        try:
            words = await api.run_in_thread(lookup, word.lower())
        except OSError as exc:
            app.notify(f"The thesaurus needs a network connection: {exc}", severity="warning")
            return
        if not words:
            app.status.flash(f"No synonyms found for {word!r}.")
            return
        choice = await app.push_screen_wait(ChoiceDialog(f"Thesaurus: {word}", [(w, w) for w in words]))
        if choice:
            editor.replace(match_case(word, choice), start, end)
            editor.focus()


def lookup(word: str) -> list[str]:
    """Synonyms first, then words with a similar meaning."""
    out: list[str] = []
    for query in ({"rel_syn": word, "max": "40"}, {"ml": word, "max": "40"}):
        url = THESAURUS_URL + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers={"User-Agent": "Inkmill"})
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        for item in data:
            candidate = str(item.get("word", ""))
            if candidate and candidate != word and candidate not in out:
                out.append(candidate)
    return out[:40]


def word_at_cursor(editor):
    """((row, start col), (row, end col), word) for the word at the cursor, or None."""
    if editor is None:
        return None
    if editor.selected_text and WORD.fullmatch(editor.selected_text):
        sel = editor.selection
        a, b = sorted([sel.start, sel.end])
        return a, b, editor.selected_text
    row, col = editor.cursor_location
    line = editor.document.get_line(row)
    for match in WORD.finditer(line):
        if match.start() <= col <= match.end():
            word = match.group().rstrip("'’")
            return (row, match.start()), (row, match.start() + len(word)), word
    return None
