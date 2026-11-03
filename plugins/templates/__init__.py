"""Templates & Journal.

New from Template... (File menu) starts a document from a template: a
chapter, a scene card, a character or location sheet, a short story, a blog
post, a poem, a query letter, or your own. Templates are Markdown files; put
yours in the ``templates`` folder beside settings.toml, or use Save as
Template... on any document. A template of the same name replaces a bundled
one.

Placeholders: {{title}}, {{date}}, {{time}}, {{weekday}}, {{author}} and
{{cursor}} (where the cursor starts). The template's own ``template`` and
``template_description`` front matter keys are removed from the new document.

Today's Journal (Alt+J) opens today's page in your journal folder, creating
it from the journal template, and adds a time heading for a new entry.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from inkmill import frontmatter
from inkmill.config import config_dir
from inkmill.screens.dialogs import ChoiceDialog, InputDialog

PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
BUNDLED = Path(__file__).parent / "templates"


def user_templates_dir() -> Path:
    return config_dir() / "templates"


def available() -> dict[str, tuple[Path, str, str]]:
    """name -> (path, label, description); your templates override bundled ones."""
    found: dict[str, tuple[Path, str, str]] = {}
    for folder in (BUNDLED, user_templates_dir()):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            try:
                meta = frontmatter.read(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            label = str(meta.get("template") or path.stem.replace("-", " ").capitalize())
            found[path.stem] = (path, label, str(meta.get("template_description", "")))
    return found


def fill(template: str, values: dict[str, str]) -> tuple[str, int]:
    """(filled text, cursor index). Unknown placeholders are left as they are."""
    text = frontmatter.update(template, {"template": None, "template_description": None})
    cursor = -1

    def sub(m: re.Match) -> str:
        key = m.group(1).lower()
        if key == "cursor":
            return "\0"
        return values.get(key, m.group(0))

    text = PLACEHOLDER.sub(sub, text)
    if "\0" in text:
        cursor = text.index("\0")
        text = text.replace("\0", "", 1).replace("\0", "")
    return text, cursor if cursor >= 0 else len(text)


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "untitled"


def register(api):
    app = api.app

    def values(title: str) -> dict[str, str]:
        now = datetime.now()
        return {
            "title": title,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "weekday": now.strftime("%A"),
            "author": str(api.settings.get("author", "")),
        }

    async def place_cursor(index: int) -> None:
        editor = app.active_editor
        if editor is not None:
            editor.cursor_location = editor.location_of(min(index, len(editor.text)))
            editor.scroll_cursor_visible(center=True)

    @api.command("templates.new", "New from Te&mplate...", menu="file",
                 description="Start a document from a template")
    async def new_from_template(app):
        templates = available()
        items = [(name, f"{label}: {desc}" if desc else label) for name, (_, label, desc) in sorted(templates.items(), key=lambda kv: kv[1][1].lower())]
        choice = await app.push_screen_wait(ChoiceDialog("New from Template", items))
        if not choice:
            return
        path, label, _ = templates[choice]
        title = ""
        raw = path.read_text(encoding="utf-8")
        if "{{title}}" in raw.replace(" ", ""):
            title = await app.push_screen_wait(InputDialog(label, "Title:", ""))
            if title is None:
                return
        if "{{author}}" in raw.replace(" ", "") and not api.settings.get("author"):
            author = await app.push_screen_wait(InputDialog(label, "Your name, for {{author}} (saved for next time):", ""))
            if author:
                api.settings["author"] = author
                api.save_settings()
        text, cursor = fill(raw, values(title or label))
        await app.new_document(text)
        await place_cursor(cursor)
        app.status.flash(f"New {label.lower()}. Save it to give it a name" + (f" (suggested: {slug(title)}.md)." if title else "."))

    @api.command("templates.save", "&Keep as Template...", menu="file",
                 enabled=lambda a: a.active_document is not None,
                 description="Make the current document a template")
    async def save_as_template(app):
        doc = app.active_document
        default = slug(doc.path.stem if doc.path else doc.title)
        name = await app.push_screen_wait(InputDialog("Save as Template", "Template name:", default))
        if not name:
            return
        folder = user_templates_dir()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{slug(name)}.md"
        text = doc.text
        if "template" not in frontmatter.read(text):
            text = frontmatter.update(text, {"template": name})
        target.write_text(text, encoding="utf-8")
        app.status.flash(f"Saved template {target.name}. Use {{{{title}}}}, {{{{date}}}} and {{{{cursor}}}} in it.")

    # -- journal ---------------------------------------------------------------

    def journal_dir() -> Path:
        configured = api.settings.get("journal_dir")
        if configured:
            return Path(str(configured)).expanduser()
        return Path.home() / "Documents" / "Journal"

    @api.command("templates.journal", "Today's &Journal", "alt+j", menu="file",
                 description="Open today's journal page and start a new entry")
    async def journal(app):
        folder = journal_dir()
        now = datetime.now()
        path = folder / now.strftime(str(api.settings.get("journal_name", "%Y-%m-%d.md")))
        created = False
        if not path.exists():
            folder.mkdir(parents=True, exist_ok=True)
            template = available().get("journal")
            raw = template[0].read_text(encoding="utf-8") if template else "# {{weekday}}, {{date}}\n\n"
            text, _ = fill(raw, values(now.strftime("%Y-%m-%d")))
            path.write_text(text, encoding="utf-8")
            created = True
        doc = await app.open_path(path)
        editor = app.active_editor
        if doc is None or editor is None:
            return
        if api.settings.get("timestamp_entries", True):
            text = editor.text.rstrip("\n")
            heading = f"## {now.strftime('%H:%M')}"
            addition = ("\n\n" if text else "") + heading + "\n\n"
            editor.insert(addition, editor.document.end)
        editor.cursor_location = editor.document.end
        editor.scroll_cursor_visible()
        app.status.flash(f"Journal: {path}")
