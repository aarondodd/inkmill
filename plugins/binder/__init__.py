"""Binder: link documents into chapters, a parent document and related notes.

Links live in each document's front matter (see ``model.py``). Commands land
in the Document menu:

* Binder... (Alt+F5) shows the binder, neighbors, related and linking
  documents, and opens any of them with Enter.
* Previous / Next Chapter (Alt+PageUp / Alt+PageDown) and Up to Binder
  (Alt+Up) jump without the list.
* Link Document..., Remove Link..., New Next Chapter..., New Binder
  Document..., Check Links, Export and Preview Manuscript.
"""

from __future__ import annotations

from pathlib import Path

from inkmill.export import Exporter
from inkmill.export.html import render_html
from inkmill.formats import write_text
from inkmill.screens.dialogs import ChoiceDialog, ConfirmDialog, InputDialog, TextDialog
from inkmill.screens.files import FileManagerScreen

from . import model
from .navigator import NavigatorScreen

RELATION_LABELS = {
    "parent": "Binder (parent document)",
    "previous": "Previous document",
    "next": "Next document",
    "related": "Related document",
}
BACK_RELATION = {"parent": "contents", "previous": "next", "next": "previous", "related": "related"}


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

    # -- commands ------------------------------------------------------------

    @api.command("binder.navigator", "&Binder...", "alt+f5", menu="document", separator=True,
                 enabled=has_path, description="Show and open linked documents")
    async def navigator(app):
        path, _ = links_here()
        chosen = await app.push_screen_wait(NavigatorScreen(path, read, write))
        if chosen:
            await open_doc(Path(chosen), "document")

    @api.command("binder.previous", "Pre&vious Chapter", "alt+pageup", menu="document", enabled=has_path)
    async def previous(app):
        _, links = links_here()
        await open_doc(model.position(links, read).previous, "previous chapter")

    @api.command("binder.next", "Ne&xt Chapter", "alt+pagedown", menu="document", enabled=has_path)
    async def next_chapter(app):
        _, links = links_here()
        await open_doc(model.position(links, read).next, "next chapter")

    @api.command("binder.parent", "&Up to Binder", "alt+up", menu="document", enabled=has_path)
    async def parent(app):
        _, links = links_here()
        await open_doc(links.parents[0] if links.parents else None, "binder for this document")

    @api.command("binder.link", "&Link Document...", menu="document", enabled=has_path)
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

    @api.command("binder.unlink", "Remove Lin&k...", menu="document", enabled=has_path)
    async def unlink(app):
        path, links = links_here()
        items = [(f"{rel}|{target}", f"{rel:<9} {model.title_of(target, read(target))}  ({model.relref(path, target)})")
                 for rel, target in links.all()]
        if not items:
            app.status.flash("This document has no links.")
            return
        choice = await app.push_screen_wait(ChoiceDialog("Remove Link", items))
        if not choice:
            return
        relation, _, target_s = choice.partition("|")
        target = Path(target_s)
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

    @api.command("binder.new_next", "New Next C&hapter...", menu="document", enabled=has_path,
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

    @api.command("binder.create", "New Binder &Document...", menu="document", enabled=has_path,
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

    @api.command("binder.check", "&Check Links", menu="document", enabled=has_path)
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

    @api.command("binder.preview", "Preview &Manuscript", menu="document", enabled=in_binder)
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

    @api.command("binder.export", "&Export Manuscript...", menu="document", enabled=in_binder)
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


def _back_question(relation: str, names: str, here: str) -> str:
    if relation == "parent":
        return f"Add {here} to the contents of {names}?"
    if relation == "previous":
        return f"Set {names} to point to {here} as its next document?"
    if relation == "next":
        return f"Set {names} to point to {here} as its previous document?"
    return f"Link {names} back to {here} as related?"
