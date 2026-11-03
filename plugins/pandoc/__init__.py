"""Export and import through pandoc.

Export via Pandoc... (File menu) writes the document, or its whole binder,
as DOCX, standard manuscript format DOCX, ODT, EPUB, PDF, RTF, LaTeX, HTML
or plain text. Import via Pandoc... opens a DOCX, ODT, RTF, HTML, EPUB,
LaTeX, Org or reStructuredText file as a new Markdown document.

Needs the pandoc program. PDF also needs a PDF engine (typst, weasyprint,
wkhtmltopdf or a LaTeX).
"""

from __future__ import annotations

from pathlib import Path

from inkmill import frontmatter
from inkmill.config import state_dir
from inkmill.documents import count_words
from inkmill.screens.dialogs import ChoiceDialog, ConfirmDialog, InputDialog, TextDialog
from inkmill.screens.files import FileManagerScreen

from . import convert


def register(api):
    app = api.app

    async def ensure_pandoc() -> bool:
        if convert.pandoc_path():
            return True
        manifest = api.manifest
        req = next((r for r in manifest.requires if r.command == "pandoc"), None) if manifest else None
        hint = req.install_hint() if req else "https://pandoc.org/installing.html"
        await app.push_screen_wait(TextDialog("Pandoc is not installed", f"Export and import need pandoc.\n\nInstall: {hint}"))
        return False

    def prepare(text: str) -> str:
        """Plain Markdown for pandoc: suggestions applied, wikilinks as text."""
        comments = api.service("comments")
        if comments is not None:
            text = comments.final(text)
        links = api.service("links")
        if links is not None:
            text = links.plain(text)
        return text

    @api.command("pandoc.export", "Export via Pan&doc...", menu="file", separator=True,
                 enabled=lambda a: a.active_document is not None,
                 description="DOCX, manuscript format, ODT, EPUB, PDF and more")
    async def export(app):
        if not await ensure_pandoc():
            return
        doc = app.active_document
        binder = api.service("binder")
        holder = binder.binder_for(doc.path) if binder is not None and doc.path is not None else None
        scope = "doc"
        if holder is not None:
            title = binder.title(holder)
            scope = await app.push_screen_wait(ChoiceDialog(
                "Export", [("binder", f"The whole binder: {title}"), ("doc", f"Only this document: {doc.title}")]
            ))
            if not scope:
                return
        fmt_id = await app.push_screen_wait(ChoiceDialog(
            "Export Format", [(f.id, f.label) for f in convert.FORMATS], api.settings.get("last_format", "docx")
        ))
        if not fmt_id:
            return
        fmt = next(f for f in convert.FORMATS if f.id == fmt_id)
        api.settings["last_format"] = fmt_id
        api.save_settings()
        if scope == "binder":
            markdown = binder.manuscript_markdown(holder)
            source = holder
        else:
            markdown = doc.text
            source = doc.path
        base = source if source is not None else Path.cwd() / doc.title
        default = base.with_suffix(fmt.extension) if fmt_id != "manuscript" else base.with_name(base.stem + "-manuscript.docx")
        answer = await app.push_screen_wait(InputDialog(f"Export {fmt.label}", "Save to:", str(default)))
        if not answer:
            return
        target = Path(answer).expanduser()
        if target.exists():
            if await app.push_screen_wait(ConfirmDialog("Replace?", f"{target.name} exists. Replace it?")) != "yes":
                return
        markdown = prepare(markdown)
        reference = None
        if fmt_id == "manuscript":
            meta = frontmatter.read(markdown)
            markdown = frontmatter.update(markdown, {k: None for k in ("title", "subtitle", "author", "date", "contact")})
            lines, body = frontmatter.split(markdown)
            markdown = (("---\n" + "\n".join(lines) + "\n---\n") if lines else "") + convert.title_page(meta, count_words(body)) + body
            font = str(api.settings.get("manuscript_font", "Courier New"))
            reference = await api.run_in_thread(convert.manuscript_reference, state_dir() / "pandoc", font)
        elif fmt_id in ("docx", "odt") and api.settings.get(f"reference_{fmt_id}"):
            reference = Path(str(api.settings[f"reference_{fmt_id}"])).expanduser()
        extra = []
        if fmt_id == "epub":
            cover = frontmatter.read(markdown).get("cover")
            if isinstance(cover, str) and cover and source is not None:
                extra.append(f"--epub-cover-image={(source.parent / cover).resolve()}")
        app.status.flash(f"Exporting {target.name}...", seconds=60)
        resource_dir = source.parent if source is not None else Path.cwd()
        try:
            await api.run_in_thread(convert.export, markdown, fmt, target, resource_dir=resource_dir,
                                    extra=extra, reference_doc=reference)
        except (convert.PandocError, OSError) as exc:
            app.status.flash("Export failed.")
            await app.push_screen_wait(TextDialog("Export failed", str(exc)))
            return
        app.status.flash(f"Exported {target}")
        if api.settings.get("open_after", False):
            from inkmill.system import open_file

            try:
                open_file(target)
            except Exception:
                pass

    @api.command("pandoc.import", "&Import via Pandoc...", menu="file",
                 description="Open a DOCX, ODT, RTF, HTML, EPUB or other file as Markdown")
    async def import_(app):
        if not await ensure_pandoc():
            return
        doc = app.active_document
        start = doc.path.parent if doc is not None and doc.path is not None else Path.home()
        picked = await app.push_screen_wait(FileManagerScreen("open", start))
        if not picked:
            return
        source = picked[0]
        if source.suffix.lower() not in convert.IMPORT_SUFFIXES:
            app.notify(f"Import reads {', '.join(sorted(convert.IMPORT_SUFFIXES))}.", severity="warning")
            return
        media = source.with_name(source.stem + "-media") if source.suffix.lower() in (".docx", ".odt", ".epub") else None
        app.status.flash(f"Importing {source.name}...", seconds=60)
        try:
            text = await api.run_in_thread(convert.import_file, source, media)
        except (convert.PandocError, OSError) as exc:
            await app.push_screen_wait(TextDialog("Import failed", str(exc)))
            return
        if media is not None and media.exists() and any(media.iterdir()):
            text = text.replace(str(media), media.name)
        await app.new_document(text)
        note = f" Images went to {media.name}/." if media is not None and media.exists() else ""
        app.status.flash(f"Imported {source.name}. Save it as Markdown next to the original.{note}")
