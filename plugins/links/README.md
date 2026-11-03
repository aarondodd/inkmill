# Links

Connect notes with `[[wikilinks]]`, follow any link without reaching for
the mouse, and see which notes link to the one you are in.

| Command | Key | What it does |
|---------|-----|--------------|
| Document > Follow Link | Alt+L | Open the link under the cursor |
| Document > Link Back | Alt+Left | Return to where you followed the last link from |
| Document > Insert Link to Note... | | Type part of a note's name, pick it, insert `[[Note]]` |
| Document > Backlinks | | Notes that link here, in the side panel |

Follow Link understands:

- `[[Note]]`, `[[Note|shown text]]` and `[[Note#Heading]]`, found by file
  name or by front matter `title`, ignoring case, anywhere in the project.
  If no note has that name yet, it offers to create one.
- Markdown links to files (`[text](../notes/ships.md#rigging)`), opening
  Markdown in Inkmill and anything else (a PDF, an image) in its usual app.
- Links to a heading in the same document (`[text](#rigging)`).
- Web addresses, opened in your browser.

## The project

Notes are searched under the project root: the nearest folder above the
document that holds a `.git` folder or an empty file named `.inkmill-root`.
Without either, the document's folder and the one above it are searched.

In HTML export and preview, `[[Note]]` becomes a link to `Note.html`.
