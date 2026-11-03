# Export via Pandoc

Turn a document, or a whole binder, into the files editors, agents and
e-book stores ask for, and bring Word or OpenDocument files in as Markdown.
Uses [pandoc](https://pandoc.org), which you install separately.

| Command | What it does |
|---------|--------------|
| File > Export via Pandoc... | Choose the document or its whole binder, a format and a file name |
| File > Import via Pandoc... | Open a DOCX, ODT, RTF, HTML, EPUB, LaTeX, Org or reStructuredText file as a new Markdown document |

| Format | Notes |
|--------|-------|
| Word document (DOCX) | Uses your own reference document if you set one |
| Standard manuscript format (DOCX) | Courier New 12 pt, double spaced, half-inch indents, one-inch margins, each chapter on a new page, and a title page with your contact details and a rounded word count |
| OpenDocument (ODT) | |
| E-book (EPUB) | One chapter per top-level heading, a table of contents, and the cover image from front matter `cover` |
| PDF | Needs a PDF engine as well: typst, weasyprint, wkhtmltopdf or a LaTeX |
| RTF, LaTeX, HTML, plain text | |

For a manuscript title page, put your details in the binder's (or the
document's) front matter:

```yaml
title: The Long Night
author: A. Writer
contact:
  - 1 Harbor Lane, Port Town
  - writer@example.com
```

Comments and suggestions from the Comments plugin are resolved as accepted,
and wikilinks become plain text, before pandoc sees the document.

Imported images are saved in a folder next to the original
(`<name>-media/`).

## Settings

```toml
[plugins.pandoc]
manuscript_font = "Courier New"          # or "Times New Roman"
reference_docx = "~/templates/house.docx"  # your styles for plain DOCX export
reference_odt = ""
open_after = false                       # open the exported file when done
```
