"""Running pandoc, and the manuscript-format reference document. No UI code."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

TIMEOUT = 300
PDF_ENGINES = ("typst", "weasyprint", "wkhtmltopdf", "xelatex", "lualatex", "pdflatex")


@dataclass
class Format:
    id: str
    label: str
    extension: str
    writer: str
    args: tuple[str, ...] = ()


FORMATS = [
    Format("docx", "Word document (DOCX)", ".docx", "docx"),
    Format("manuscript", "Standard manuscript format (DOCX)", ".docx", "docx"),
    Format("odt", "OpenDocument text (ODT)", ".odt", "odt"),
    Format("epub", "E-book (EPUB)", ".epub", "epub3", ("--toc", "--split-level=1")),
    Format("pdf", "PDF", ".pdf", "pdf"),
    Format("rtf", "Rich Text (RTF)", ".rtf", "rtf", ("--standalone",)),
    Format("latex", "LaTeX", ".tex", "latex", ("--standalone",)),
    Format("html", "HTML (pandoc's own)", ".html", "html5", ("--standalone", "--embed-resources")),
    Format("plain", "Plain text", ".txt", "plain", ("--wrap=auto",)),
]

IMPORT_SUFFIXES = {".docx", ".odt", ".rtf", ".html", ".htm", ".epub", ".tex", ".org", ".rst", ".textile", ".fb2", ".ipynb"}

# Inkmill's Markdown: CommonMark with footnotes, tables, task lists, definition
# lists, strikethrough and front matter; "alerts" is GitHub's > [!NOTE].
READER = "commonmark_x+alerts"
FALLBACK_READER = "commonmark_x"
WRITER_MD = "gfm+footnotes+yaml_metadata_block"


class PandocError(Exception):
    pass


def pandoc_path() -> str | None:
    return shutil.which("pandoc")


def pdf_engine() -> str | None:
    for engine in PDF_ENGINES:
        if shutil.which(engine):
            return engine
    return None


def version() -> str:
    exe = pandoc_path()
    if exe is None:
        return ""
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout
    return out.split("\n", 1)[0].replace("pandoc", "").strip()


def run(args: list[str], *, stdin: str | None = None) -> str:
    exe = pandoc_path()
    if exe is None:
        raise PandocError("pandoc is not installed")
    try:
        proc = subprocess.run(
            [exe, *args], input=stdin.encode("utf-8") if stdin is not None else None,
            capture_output=True, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise PandocError(f"pandoc took longer than {TIMEOUT} seconds") from exc
    if proc.returncode != 0:
        raise PandocError(proc.stderr.decode("utf-8", "replace").strip() or f"pandoc exited with {proc.returncode}")
    return proc.stdout.decode("utf-8", "replace")


def export(markdown: str, fmt: Format, target: Path, *, resource_dir: Path, extra: list[str] | None = None,
           reference_doc: Path | None = None) -> None:
    args = ["--from", READER, "--to", fmt.writer, "--output", str(target), "--resource-path", str(resource_dir), *fmt.args]
    if fmt.id == "pdf":
        engine = pdf_engine()
        if engine is None:
            raise PandocError(
                "PDF needs a PDF engine as well as pandoc: install one of "
                + ", ".join(PDF_ENGINES) + ". Typst is the smallest. Or use Preview in Browser (F9) and print to PDF."
            )
        args.append(f"--pdf-engine={engine}")
    if reference_doc is not None:
        args.append(f"--reference-doc={reference_doc}")
    args += extra or []
    try:
        run(args, stdin=markdown)
    except PandocError as exc:
        if "alerts" in str(exc) and "extension" in str(exc).lower():
            args[1] = FALLBACK_READER
            run(args, stdin=markdown)
        else:
            raise


def import_file(source: Path, media_dir: Path | None = None) -> str:
    args = [str(source), "--to", WRITER_MD, "--wrap=none", "--standalone"]
    if media_dir is not None:
        args.append(f"--extract-media={media_dir}")
    return run(args)


# -- standard manuscript format ---------------------------------------------------


def manuscript_reference(cache_dir: Path, font: str = "Courier New") -> Path:
    """A reference.docx for standard manuscript format, built from pandoc's own.

    12 pt type, double spaced, half-inch first-line indents, one-inch margins,
    chapter headings centered on a new page. Rebuilt when pandoc or the font
    changes.
    """
    key = re.sub(r"[^\w.]+", "-", f"{version()}-{font}")
    target = cache_dir / f"manuscript-{key}.docx"
    if target.exists():
        return target
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "reference.docx"
        exe = pandoc_path()
        if exe is None:
            raise PandocError("pandoc is not installed")
        subprocess.run([exe, "-o", str(base), "--print-default-data-file", "reference.docx"], check=True,
                       capture_output=True, timeout=60)
        with zipfile.ZipFile(base) as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/styles.xml":
                    data = _manuscript_styles(data.decode("utf-8"), font).encode("utf-8")
                elif item.filename == "word/document.xml":
                    data = _manuscript_page(data.decode("utf-8")).encode("utf-8")
                zout.writestr(item, data)
    return target


def _manuscript_styles(xml: str, font: str) -> str:
    fonts = f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:eastAsia="{font}" w:cs="{font}" />'
    xml = re.sub(r"<w:rFonts [^>]*/>", fonts, xml)
    xml = re.sub(r'<w:sz w:val="\d+" />', '<w:sz w:val="24" />', xml)
    xml = re.sub(r'<w:szCs w:val="\d+" />', '<w:szCs w:val="24" />', xml)
    xml = re.sub(r"<w:color [^>]*/>", '<w:color w:val="000000" />', xml)
    xml = re.sub(r"<w:pPrDefault>.*?</w:pPrDefault>",
                 '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="480" w:lineRule="auto" /></w:pPr></w:pPrDefault>',
                 xml, flags=re.DOTALL)

    def style(style_id: str, transform) -> None:
        nonlocal xml
        pattern = re.compile(r'(<w:style [^>]*w:styleId="' + style_id + r'"[^>]*>)(.*?)(</w:style>)', re.DOTALL)
        xml = pattern.sub(lambda m: m.group(1) + transform(m.group(2)) + m.group(3), xml, count=1)

    def set_ppr(inner: str, ppr: str) -> str:
        inner = re.sub(r"<w:pPr>.*?</w:pPr>|<w:pPr\s*/>", "", inner, flags=re.DOTALL)
        anchor = inner.find("<w:rPr>")
        block = f"<w:pPr>{ppr}</w:pPr>"
        return inner[:anchor] + block + inner[anchor:] if anchor != -1 else inner + block

    body = '<w:spacing w:before="0" w:after="0" w:line="480" w:lineRule="auto" /><w:ind w:firstLine="720" />'
    style("BodyText", lambda inner: set_ppr(inner, body))
    style("FirstParagraph", lambda inner: set_ppr(inner, body))
    style("Heading1", lambda inner: set_ppr(inner, '<w:keepNext /><w:pageBreakBefore /><w:spacing w:before="2880" w:after="480" /><w:jc w:val="center" /><w:outlineLvl w:val="0" />'))
    style("Heading2", lambda inner: set_ppr(inner, '<w:keepNext /><w:spacing w:before="480" w:after="240" /><w:jc w:val="center" /><w:outlineLvl w:val="1" />'))
    style("Title", lambda inner: set_ppr(inner, '<w:spacing w:before="2880" w:after="240" /><w:jc w:val="center" />'))
    xml = xml.replace("<w:b />", "").replace("<w:bCs />", "").replace("<w:i />", "")
    return xml


def _manuscript_page(xml: str) -> str:
    page = ('<w:pgSz w:w="12240" w:h="15840" />'
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0" />')
    return re.sub(r"(<w:sectPr>)", r"\1" + page, xml, count=1)


def title_page(meta: dict, words: int) -> str:
    """Markdown for a manuscript title page: contact block, word count, title and byline."""
    author = str(meta.get("author") or "")
    contact = meta.get("contact") or []
    if isinstance(contact, str):
        contact = [contact]
    lines = [str(line) for line in [author, *contact] if line]
    rounded = int(round(words, -2 if words >= 1000 else -1)) if words else 0
    block = "\\\n".join(lines)
    title = str(meta.get("title") or "")
    parts = [block, f"About {rounded:,} words" if rounded else "", "", f"::: {{custom-style=\"Title\"}}\n{title}\n:::" if title else "",
             f"::: {{custom-style=\"Author\"}}\nby {author}\n:::" if author else "",
             "```{=openxml}\n<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>\n```"]
    return "\n\n".join(p for p in parts if p) + "\n\n"
