"""Binder: chapters, an overall document, related notes and research.

Links live in each document's front matter (see ``model.py``). Commands are
in the Binder menu (Alt+I):

* Binder... (Alt+F5) shows the binder, neighbors, related, research and
  linking documents, and opens any of them with Enter.
* Binder Outline... shows every chapter with its status, words, target and
  synopsis, and edits them in place.
* Previous / Next Chapter (Alt+PageUp / Alt+PageDown) and Up to Binder
  (Alt+Up) jump without the list.
* Set Status, Set Synopsis, Link Document, Remove Link, New Next Chapter,
  New Binder Document.
* New Research Note, Clip Web Page and Add Research keep research beside the
  work without making it part of the manuscript.
* Check Links, Preview and Export Manuscript.
"""

from __future__ import annotations

from pathlib import Path

from inkmill.export import Exporter
from inkmill.export.html import render_html
from inkmill.formats import write_text
from inkmill.screens.dialogs import ChoiceDialog, ConfirmDialog, InputDialog, TextDialog
from inkmill.screens.files import FileManagerScreen

from . import clip, model
from .navigator import NavigatorScreen
from .outline import BinderOutlineScreen

RELATION_LABELS = {
    "parent": "Binder (parent document)",
    "previous": "Previous document",
    "next": "Next document",
    "related": "Related document",
    "research": "Research (for this document's binder)",
}
BACK_RELATION = {"parent": "contents", "previous": "next", "next": "previous", "related": "related", "research": None}


def register(api):
    app = api.app
    cache: dict[str, tuple[float, str]] = {}

    def read(path: Path) -> str | None:
        """Text of ``path``: the open buffer if it is open, else the file."""
        doc = app.docs.find_path(path)
        if doc is not None:
            return doc.text
        try:
            stat = path.stat()
        except OSError:
            return None
        key = str(path)
        hit = cache.get(key)
        if hit and hit[0] == stat.st_mtime:
            return hit[1]
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return None
        cache[key] = (stat.st_mtime, text)
        return text

    def write(path: Path, text: str) -> None:
        """Change a document's front matter.

        An open document gets the change as an undoable edit, and is saved
        too when it had no other unsaved changes. A closed file is written.
        """
        doc = app.docs.find_path(path)
        if doc is not None:
            was_clean = not doc.dirty
            if text != doc.text:
                app.replace_document_text(doc, text)
                if was_clean:
                    app.save_document(doc)
            return
        write_text(path, text)
        cache.pop(str(path), None)

    def current_path():
        doc = app.active_document
        return model.norm(doc.path) if doc is not None and doc.path is not None else None

    def has_path(_app) -> bool:
        return current_path() is not None

    def links_here():
        path = current_path()
        return (path, model.read_links(path, read(path))) if path else (None, None)

    async def open_doc(path: Path | None, what: str) -> None:
        if path is None:
            app.status.flash(f"No {what}.")
            return
        if not path.exists():
            app.notify(f"{path.name} does not exist. Check Links finds broken links.", severity="warning")
            return
        await app.open_path(path)

    async def open_item(item: str) -> None:
        """Open what the navigator picked: a document, folder, other file or web address."""
        if item.startswith("url|"):
            from inkmill.system import open_url

            try:
                open_url(item.removeprefix("url|"))
            except RuntimeError as exc:
                app.notify(str(exc), severity="warning")
            return
        path = Path(item)
        if path.is_dir():
            picked = await app.push_screen_wait(FileManagerScreen("open", path))
            for chosen in picked or []:
                await app.open_path(chosen)
            return
        if path.exists() and path.suffix.lower() not in model.DOC_SUFFIXES:
            from inkmill.system import open_file

            try:
                open_file(path)
            except RuntimeError as exc:
                app.notify(str(exc), severity="warning")
            return
        await open_doc(path, "document")

    def statuses() -> list[str]:
        custom = api.settings.get("statuses")
        return [str(s) for s in custom] if isinstance(custom, list) and custom else list(model.STATUSES)

    # -- commands ------------------------------------------------------------

    api.add_menu("binder", "B&inder")

    @api.command("binder.navigator", "&Binder...", "alt+f5", menu="binder",
                 enabled=has_path, description="Show and open linked documents")
    async def navigator(app):
        path, _ = links_here()
        chosen = await app.push_screen_wait(NavigatorScreen(path, read, write))
        if chosen:
            await open_item(chosen)

    @api.command("binder.outline", "Binder &Outline...", menu="binder", enabled=lambda a: in_binder(a),
                 description="Every chapter with status, words, target and synopsis")
    async def outline(app):
        holder = binder_for(current_path())
        chosen = await app.push_screen_wait(BinderOutlineScreen(holder, read, write, statuses(), _pace))
        api.refresh_status()
        if chosen:
            await open_doc(Path(chosen), "chapter")

    @api.command("binder.previous", "Pre&vious Chapter", "alt+pageup", menu="binder", enabled=has_path)
    async def previous(app):
        _, links = links_here()
        await open_doc(model.position(links, read).previous, "previous chapter")

    @api.command("binder.next", "Ne&xt Chapter", "alt+pagedown", menu="binder", enabled=has_path)
    async def next_chapter(app):
        _, links = links_here()
        await open_doc(model.position(links, read).next, "next chapter")

    @api.command("binder.parent", "&Up to Binder", "alt+up", menu="binder", enabled=has_path)
    async def parent(app):
        _, links = links_here()
        await open_doc(links.parents[0] if links.parents else None, "binder for this document")

    @api.command("binder.status", "Set &Status...", menu="binder", separator=True, enabled=has_path,
                 description="Idea, outline, draft, revised, final, or your own list")
    async def set_status(app):
        path, _ = links_here()
        current = model.field_value(read(path), "status")
        items = [(s, s) for s in statuses()] + [("", "(none)")]
        choice = await app.push_screen_wait(ChoiceDialog(f"Status: {path.name}", items, current))
        if choice is not None:
            write(path, model.set_field(read(path) or "", "status", choice or None))
            app.status.flash(f"Status: {choice or 'none'}")

    @api.command("binder.synopsis", "Set S&ynopsis...", menu="binder", enabled=has_path)
    async def set_synopsis(app):
        path, _ = links_here()
        current = model.field_value(read(path), "synopsis")
        answer = await app.push_screen_wait(InputDialog(f"Synopsis: {path.name}", "One or two sentences:", current))
        if answer is not None:
            write(path, model.set_field(read(path) or "", "synopsis", answer.strip() or None))

    @api.command("binder.link", "&Link Document...", menu="binder", separator=True, enabled=has_path)
    async def link(app):
        path, links = links_here()
        relation = await app.push_screen_wait(ChoiceDialog("Link Document", list(RELATION_LABELS.items()), prompt="This document's:"))
        if not relation:
            return
        picked = await app.push_screen_wait(FileManagerScreen("open", path.parent))
        if not picked:
            return
        targets = [model.norm(p) for p in picked if not model.same(p, path)]
        if relation in ("previous", "next", "parent"):
            targets = targets[:1]
        if not targets:
            return
        if relation == "research":
            holder = binder_for(path) or path
            text = read(holder) or ""
            for target in targets:
                text = model.add_relation(text, holder, "research", target)
            write(holder, text)
            app.status.flash(f"Added {len(targets)} research item(s) to {holder.name}.")
            return
        text = read(path) or ""
        for target in targets:
            text = model.add_relation(text, path, relation, target)
        write(path, text)
        names = ", ".join(t.name for t in targets)
        back = await app.push_screen_wait(
            ConfirmDialog("Link back?", _back_question(relation, names, path.name))
        )
        if back == "yes":
            for target in targets:
                if not target.exists():
                    continue
                other = read(target) or ""
                after = links.previous if relation == "parent" else None
                write(target, model.add_relation(other, target, BACK_RELATION[relation], path, after=after))
        app.status.flash(f"Linked {names} as {RELATION_LABELS[relation].lower()}.")
        api.refresh_status()

    @api.command("binder.unlink", "Remove Lin&k...", menu="binder", enabled=has_path)
    async def unlink(app):
        path, links = links_here()
        items = [(f"{rel}|{target}", f"{rel:<9} {model.title_of(target, read(target))}  ({model.relref(path, target)})")
                 for rel, target in links.all()]
        items += [(f"research|{url}", f"research  {url}") for url in links.research_urls]
        if not items:
            app.status.flash("This document has no links.")
            return
        choice = await app.push_screen_wait(ChoiceDialog("Remove Link", items))
        if not choice:
            return
        relation, _, target_s = choice.partition("|")
        target = Path(target_s)
        if relation == "research":
            write(path, model.remove_relation(read(path) or "", path, relation, target))
            app.status.flash("Research link removed.")
            return
        write(path, model.remove_relation(read(path) or "", path, relation, target))
        back = BACK_RELATION.get(relation, "parent" if relation == "contents" else None)
        if back and target.exists():
            other = read(target) or ""
            if any(model.same(t, path) for r, t in model.read_links(target, other).all() if r == back):
                answer = await app.push_screen_wait(ConfirmDialog("Remove back link?", f"Also remove the link back from {target.name}?"))
                if answer == "yes":
                    write(target, model.remove_relation(other, target, back, path))
        app.status.flash("Link removed.")
        api.refresh_status()

    @api.command("binder.new_next", "New Next C&hapter...", menu="binder", enabled=has_path,
                 description="Create the next document and link it in place")
    async def new_next(app):
        path, links = links_here()
        name = await app.push_screen_wait(InputDialog("New Next Chapter", f"File name (in {path.parent.name}):", model.next_name(path)))
        if not name:
            return
        target = model.norm(path.parent / name)
        if target.suffix == "":
            target = target.with_suffix(path.suffix or ".md")
        if target.exists():
            app.notify(f"{target.name} already exists.", severity="error")
            return
        pos = model.position(links, read)
        text = ""
        if pos.binder is not None and pos.index >= 0:
            text = model.set_relation(text, target, "parent", [pos.binder])
            write_text(target, text)
            binder_text = read(pos.binder) or ""
            write(pos.binder, model.add_relation(binder_text, pos.binder, "contents", target, after=path))
        else:
            if links.parents:
                text = model.set_relation(text, target, "parent", links.parents)
            text = model.set_relation(text, target, "previous", [path])
            old_next = links.next
            if old_next is not None:
                text = model.set_relation(text, target, "next", [old_next])
            write_text(target, text)
            write(path, model.set_relation(read(path) or "", path, "next", [target]))
            if old_next is not None and old_next.exists():
                write(old_next, model.set_relation(read(old_next) or "", old_next, "previous", [target]))
        await app.open_path(target)
        app.status.flash(f"Created {target.name}.")

    @api.command("binder.create", "New Binder &Document...", menu="binder", enabled=has_path,
                 description="Create an overall document listing this one as its first chapter")
    async def create(app):
        path, links = links_here()
        default = f"{path.parent.name or 'binder'}.md"
        name = await app.push_screen_wait(InputDialog("New Binder Document", f"File name (in {path.parent.name}):", default))
        if not name:
            return
        target = model.norm(path.parent / name)
        if target.exists():
            app.notify(f"{target.name} already exists. Use Link Document to make it the binder.", severity="error")
            return
        title = path.parent.name.replace("-", " ").replace("_", " ").title() or "Binder"
        text = model.set_relation(f"---\ntitle: {title}\n---\n", target, "contents", [path])
        write_text(target, text)
        write(path, model.add_relation(read(path) or "", path, "parent", target))
        app.status.flash(f"Created {target.name} with this document as its first entry.")
        api.refresh_status()

    # -- research --------------------------------------------------------------

    def research_home(path: Path) -> tuple[Path, Path]:
        """(binder or document that lists research, folder new notes go in)."""
        holder = binder_for(path) or path
        folder = holder.parent / str(api.settings.get("research_folder", "research"))
        return holder, folder

    def add_note(path: Path, title: str, body: str, fields: dict[str, str] | None = None) -> Path:
        """Write a new research note beside ``path``'s binder (or ``path``
        itself, outside a binder) and list it there. Never overwrites."""
        holder, folder = research_home(model.norm(path))
        stem = _slug(title)[:60]
        target = folder / f"{stem}.md"
        n = 2
        while target.exists():
            target = folder / f"{stem}-{n}.md"
            n += 1
        folder.mkdir(parents=True, exist_ok=True)
        head = f'---\ntitle: "{title.replace(chr(34), chr(39))}"\ntype: research\n'
        head += "".join(f"{key}: {value}\n" for key, value in (fields or {}).items())
        text = model.set_relation(head + "---\n" + body, target, "parent", [holder])
        write_text(target, text)
        write(holder, model.add_relation(read(holder) or "", holder, "research", target))
        return target

    @api.command("binder.note", "New Research &Note...", menu="binder", separator=True, enabled=has_path,
                 description="A note listed under the binder's research, not part of the manuscript")
    async def new_note(app):
        path, _ = links_here()
        holder, folder = research_home(path)
        title = await app.push_screen_wait(InputDialog("New Research Note", "Title:", ""))
        if not title:
            return
        target = folder / f"{_slug(title)}.md"
        if target.exists():
            app.notify(f"{target.name} already exists; opening it.", severity="warning")
        else:
            folder.mkdir(parents=True, exist_ok=True)
            text = model.set_relation(f'---\ntitle: "{title}"\ntype: research\n---\n# {title}\n\n', target, "parent", [holder])
            write_text(target, text)
            write(holder, model.add_relation(read(holder) or "", holder, "research", target))
        await app.open_path(target)

    @api.command("binder.clip", "&Clip Web Page...", menu="binder", enabled=has_path,
                 description="Save a web page's text as a research note")
    async def clip_page(app):
        path, _ = links_here()
        holder, folder = research_home(path)
        url = await app.push_screen_wait(InputDialog("Clip Web Page", "Address:", "https://"))
        if not url or url.strip() in ("https://", "http://"):
            return
        url = url.strip()
        app.status.flash(f"Fetching {url}...", seconds=30)
        try:
            title, body = await api.run_in_thread(clip.fetch, url)
        except Exception as exc:
            app.notify(f"Could not fetch the page: {exc}", severity="error")
            return
        title = title or url
        from datetime import date

        target = add_note(path, title, f"Source: <{url}>\n\n" + body,
                          {"source": url, "clipped": date.today().isoformat()})
        await app.open_path(target)
        app.status.flash(f"Clipped {len(body.split()):,} words into {target.name}.")

    @api.command("binder.research", "Add &Research...", menu="binder", enabled=has_path,
                 description="List a file, folder or web address under the binder's research")
    async def add_research(app):
        path, _ = links_here()
        holder, _folder = research_home(path)
        kind = await app.push_screen_wait(ChoiceDialog("Add Research", [("file", "A file or folder"), ("url", "A web address")]))
        if kind == "url":
            url = await app.push_screen_wait(InputDialog("Add Research", "Address:", "https://"))
            if url and url.strip() not in ("https://", "http://"):
                write(holder, model.add_relation(read(holder) or "", holder, "research", url.strip()))
                app.status.flash("Added to research.")
        elif kind == "file":
            picked = await app.push_screen_wait(FileManagerScreen("open", holder.parent))
            if picked:
                text = read(holder) or ""
                for item in picked:
                    text = model.add_relation(text, holder, "research", model.norm(item))
                write(holder, text)
                app.status.flash(f"Added {len(picked)} item(s) to research.")

    @api.command("binder.check", "Ch&eck Links", menu="binder", separator=True, enabled=has_path)
    async def check(app):
        path, links = links_here()
        docs = [path] + (model.leaves(path, read) if links.is_binder else [])
        lines = []
        for doc in docs:
            for relation, target in model.broken(doc, read(doc)):
                lines.append(f"{doc.name}: {relation} -> {model.relref(doc, target)} (missing)")
        if links.is_binder:
            for item in links.contents:
                child = model.read_links(item, read(item))
                if item.exists() and not any(model.same(p, path) for p in child.parents):
                    lines.append(f"{item.name}: listed in contents but does not name {path.name} as its parent")
        body = "\n".join(lines) if lines else "All links point at existing documents."
        await app.push_screen_wait(TextDialog("Check Links", body))

    # -- manuscript ----------------------------------------------------------

    def binder_for(path: Path) -> Path | None:
        links = model.read_links(path, read(path))
        if links.is_binder:
            return path
        return model.position(links, read).binder

    def manuscript(doc, settings) -> str:
        if doc.path is None:
            raise ValueError("save the document first")
        binder = binder_for(model.norm(doc.path))
        if binder is None:
            raise ValueError("this document is not in a binder")
        text = model.manuscript_markdown(
            binder,
            read,
            include_binder_text=bool(api.settings.get("include_binder_text", False)),
            add_titles=bool(api.settings.get("chapter_titles", True)),
        )
        return render_html(text, style=settings.export_style, typographer=settings.typographer, fallback_title=binder.stem)

    api.register_exporter(Exporter("manuscript", "Manuscript HTML (whole binder)", ".manuscript.html", manuscript))

    def in_binder(_app) -> bool:
        path = current_path()
        return path is not None and binder_for(path) is not None

    @api.command("binder.preview", "&Preview Manuscript", menu="binder", enabled=in_binder)
    async def preview_manuscript(app):
        from inkmill.system import open_in_browser

        doc = app.active_document
        target = app.preview_dir / f"manuscript-{doc.id}.html"
        try:
            target.write_text(manuscript(doc, app.settings), encoding="utf-8")
        except ValueError as exc:
            app.notify(str(exc), severity="warning")
            return
        try:
            how = open_in_browser(target, app.preview_server)
        except RuntimeError as exc:
            app.notify(f"Manuscript written to {target}, but {exc}.", severity="warning")
            return
        app.status.flash(f"Manuscript opened ({how}).")

    @api.command("binder.export", "Export &Manuscript...", menu="binder", enabled=in_binder)
    async def export_manuscript(app):
        doc = app.active_document
        binder = binder_for(model.norm(doc.path))
        default = str(binder.with_suffix(".html"))
        answer = await app.push_screen_wait(InputDialog("Export Manuscript", f"Style: {app.settings.export_style}.  Save to:", default))
        if not answer:
            return
        target = Path(answer).expanduser()
        target.write_text(manuscript(doc, app.settings), encoding="utf-8")
        app.status.flash(f"Exported {target}")

    # -- for other plugins -----------------------------------------------------

    class Service:
        """What Progress, Export via Pandoc and the AI Assistant use."""

        @staticmethod
        def binder_for(path: Path) -> Path | None:
            return binder_for(model.norm(path))

        @staticmethod
        def title(path: Path) -> str:
            return model.title_of(path, read(path))

        @staticmethod
        def chapters(binder: Path) -> list[Path]:
            return model.leaves(binder, read)

        @staticmethod
        def read(path: Path) -> str | None:
            return read(path)

        @staticmethod
        def manuscript_markdown(binder: Path) -> str:
            return model.manuscript_markdown(
                binder, read,
                include_binder_text=bool(api.settings.get("include_binder_text", False)),
                add_titles=bool(api.settings.get("chapter_titles", True)),
            )

        @staticmethod
        def research(binder: Path) -> tuple[list[Path], list[str]]:
            links = model.read_links(binder, read(binder))
            files: list[Path] = []
            for item in links.research:
                if item.is_dir():
                    files += sorted(p for p in item.rglob("*") if p.suffix.lower() in model.DOC_SUFFIXES)
                elif item.suffix.lower() in model.DOC_SUFFIXES:
                    files.append(item)
            return files, list(links.research_urls)

        @staticmethod
        def project(path: Path) -> dict | None:
            holder = binder_for(model.norm(path))
            if holder is None:
                return None
            text = read(holder)
            target = model.field_value(text, "target")
            if not target:
                return None
            return {"title": model.title_of(holder, text), "words": model.binder_words(holder, read),
                    "target": target, "deadline": model.field_value(text, "deadline")}

        @staticmethod
        def add_research_note(path: Path, title: str, body: str, fields: dict[str, str] | None = None) -> Path:
            """A new note in the research folder of ``path``'s binder, listed
            under its research (outside a binder, under ``path``'s own)."""
            return add_note(path, title, body, fields)

        @staticmethod
        def set_field(path: Path, key: str, value: str | None) -> None:
            write(model.norm(path), model.set_field(read(path) or "", key, value))

    api.provide("binder", Service())

    # -- status line and renames -----------------------------------------------

    @api.status_segment
    def segment(app):
        if not api.settings.get("status", True):
            return None
        path = current_path()
        if path is None:
            return None
        links = model.read_links(path, read(path))
        if links.is_binder:
            return f"Binder {len(links.contents)} ch ({model.binder_words(path, read):,} total)"
        pos = model.position(links, read)
        if pos.binder is None or pos.index < 0:
            return None
        return f"Ch {pos.index + 1}/{pos.total} ({model.binder_words(pos.binder, read):,} total)"

    @api.on("file_moved")
    def moved(app, old: Path, new: Path) -> None:
        old, new = model.norm(old), model.norm(new)
        if new.suffix.lower() not in model.DOC_SUFFIXES:
            return
        # The moved document's own references are relative to its folder.
        own = read(new)
        if own is not None and old.parent != new.parent:
            rebased = model.rebase(own, old, new)
            if rebased != own:
                write(new, rebased)
        # Documents that pointed at the old name.
        targets = {model.norm(p) for _, p in model.read_links(new, read(new)).all()}
        folders = [old.parent, new.parent, old.parent.parent]
        for _, other in model.backlinks(old, read, folders):
            targets.add(other)
        changed = 0
        for other in targets:
            if model.same(other, new) or not other.exists():
                continue
            text = read(other)
            if text is None:
                continue
            updated = model.rewrite_target(text, other, old, new)
            if updated != text:
                write(other, updated)
                changed += 1
        if changed:
            app.notify(f"Updated links in {changed} document(s) for the rename.", title="Binder")


def _slug(title: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "note"


def _pace(words: int, target: int, deadline: str) -> str | None:
    from datetime import date

    try:
        end = date.fromisoformat(deadline)
    except (TypeError, ValueError):
        return None
    days = (end - date.today()).days + 1
    remaining = target - words
    if remaining <= 0:
        return "target reached"
    if days <= 0:
        return f"{remaining:,} words past the deadline"
    return f"{-(-remaining // days):,} words a day to finish by {deadline}"


def _back_question(relation: str, names: str, here: str) -> str:
    if relation == "parent":
        return f"Add {here} to the contents of {names}?"
    if relation == "previous":
        return f"Set {names} to point to {here} as its next document?"
    if relation == "next":
        return f"Set {names} to point to {here} as its previous document?"
    return f"Link {names} back to {here} as related?"
