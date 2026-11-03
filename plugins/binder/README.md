# Binder

Write long work as separate documents and keep them connected. A chapter
knows its binder (the overall document), the binder knows the chapters in
order, and any document can list related ones. Everything is stored in
front matter, so the files stay plain Markdown that other tools can read.

## Front matter

```yaml
---
title: The Crossing
parent: ../the-long-night.md
related: [notes/characters.md, research/ships.md]
---
```

The binder holds the reading order:

```yaml
---
title: The Long Night
author: A. Writer
contents:
  - chapters/arrival.md
  - chapters/the-crossing.md
  - chapters/the-storm.md
---
```

| Key | Meaning |
|-----|---------|
| `parent` | The binder this document belongs to. A list is allowed. |
| `contents` | In a binder: its documents in order. An entry can itself be a binder (a part holding chapters). |
| `previous`, `next` | Explicit neighbors. Use them to chain documents with no binder; they win over the binder's order. |
| `related` | Other documents this one relates to. |

Paths are relative to the document's own folder and use forward slashes, so
they work on Windows, Linux and Android and survive moving the whole
project. `up` and `prev` are read as `parent` and `previous`. Inkmill only
rewrites the keys it manages; the rest of your front matter, comments
included, is left alone.

## Commands

In the Document menu:

| Command | Key | What it does |
|---------|-----|--------------|
| Binder... | Alt+F5 | The binder, its contents, neighbors, related and linking documents |
| Previous Chapter / Next Chapter | Alt+PgUp / Alt+PgDn | Open the neighbor |
| Up to Binder | Alt+Up | Open the binder |
| Link Document... | | Set the binder, previous, next or a related document |
| Remove Link... | | Remove one, and optionally the link back |
| New Next Chapter... | | Create the next file (`chapter-03.md` after `chapter-02.md`) and put it in order |
| New Binder Document... | | Start a binder with this document as its first entry |
| Check Links | | Report links to missing files |
| Preview Manuscript / Export Manuscript... | | The whole binder as one styled HTML page |

In the Binder list, Enter opens the highlighted document and `[` and `]`
move a chapter up or down in the binder.

Link Document asks whether to update the other file too, so adding a
binder as `parent` also adds this document to the binder's `contents`.
Renaming or moving a file in List Files updates the links that pointed at
it from the documents it links to and from documents in the same folder or
the folder above. The Binder list's "Linked from" section looks in the
document's folder, the folder above and the folders directly below.

Some terminals do not pass Alt+PgUp, Alt+PgDn or Alt+Up through. The Binder
list (Alt+F5) always works, and any key can be rebound under `[keys]`.

## The manuscript

Preview and Export Manuscript join every chapter of the binder, in order,
into one HTML page using the current HTML style. Chapters without a heading
get their title as one. Footnotes stay with their own chapter even when two
chapters both use `[^1]`. Page breaks fall between chapters when printing.

The status line shows `Ch 2/14 (48,900 total)` in a chapter, and the binder
word count in the binder itself.

## Settings

```toml
[plugins.binder]
status = true                # chapter number and total in the status line
chapter_titles = true        # add a heading to chapters that have none
include_binder_text = false  # put the binder's own body first in the manuscript
```
