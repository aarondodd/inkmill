# Changelog

## 0.3.0 (unreleased)

Writing tools, as plugins:

- Spelling & Thesaurus: WordPerfect-style spell check (Ctrl+F2), underlines
  as you write, an offline US English dictionary plus your own lists, and a
  thesaurus (Alt+F1).
- Prose Check: passive voice, adverbs, filler, wordy phrases, cliches,
  repeats and long sentences with readability numbers; adds Vale's findings.
- Outline (F8): headings in the side panel; move, promote and demote whole
  sections.
- Binder 1.1: research (notes, clipped web pages, files, folders, links), a
  Binder Outline with status, words, targets and synopses, chapter status
  and synopsis commands, and a Binder menu (Alt+I).
- Links: wikilinks, Follow Link (Alt+L) for any link, Link Back, backlinks,
  a note picker; wikilinks become links in HTML export.
- Comments & Track Changes: CriticMarkup comments and suggestions with a
  review list, Accept All and Reject All, shown or resolved in exports.
- Snapshots (Ctrl+F5): named versions with a word-level comparison and
  restore.
- Progress (Ctrl+F8): daily words against a goal, streaks, sprints, history
  and project pace. Replaces Word Goal, which moves back to `examples/`.
- Templates & Journal: bundled and personal templates with placeholders,
  and a daily journal page (Alt+J).
- Export via Pandoc: DOCX, standard manuscript format, ODT, EPUB, PDF, RTF
  and LaTeX for a document or a whole binder; import from Word and others.
- AI Assistant: opt-in feedback, rewrites, synopses and a binder-wide
  continuity check through Claude, Ollama or any OpenAI-compatible server,
  with streaming replies and prompt caching.

Core:

- A side panel that plugins fill on demand; Ctrl+T switches to it.
- Plugin APIs for editor highlights, Markdown export extensions, services
  between plugins, and the `document_changed` and `panel_closed` events;
  `open_url`, `open_file` and `mask_non_prose` helpers.
- Plugin manifests declare outside programs with `[[requires]]`; View >
  Plugins checks them, shows install commands for your platform, and asks
  before installing a plugin whose program is missing.
- Fixed: Revert and Recover shared the V accelerator in the File menu.

## 0.2.0 (unreleased)

- View > Plugins: browse, install, update, disable, remove and roll back
  plugins from the index in this repository, online or from a local clone.
  Files are verified against SHA-256 hashes in the index; plugins declare
  the Inkmill versions they support.
- Restart in place (after plugin changes, or Restart Inkmill in the
  palette), keeping open documents and unsaved text.
- Plugin manifests (`plugin.toml`) and folder plugins with several modules;
  `inkmill --plugins` lists them.
- Plugin API: events (`api.on`), status line segments, `run_in_thread`, and
  `inkmill.frontmatter` for editing front matter in place.
- Documents changed on disk by another program reload when you switch to
  them, or warn when they have unsaved edits.
- New plugins: Binder (chapters, binder documents, related documents,
  manuscript export), Git Sync (commit, pull, push) and Themes (ten themes,
  a live-preview gallery, user themes as TOML files). Word Goal moved from
  `examples/` into `plugins/`.
- Any Textual theme (Nord, Gruvbox, Dracula, ...) now gets menus, dialogs
  and status colors worked out from its own palette instead of
  WordPerfect's gray. `inkmill.themes.make_theme` builds a complete theme
  from four colors.
- Dialogs and menus draw over the document instead of a blank screen.

## 0.1.0 (unreleased)

First version.

- Hidden-until-needed menu bar (Esc, F10, Alt+=) with File, Edit, Format,
  Document, View and Help menus, plus a command palette on Ctrl+P.
- WordPerfect 5.1 blue screen theme by default; grinder, paper, amber and
  phosphor themes included.
- Several documents open at once, each with its own undo history.
- List Files (F5) with live preview, marking, open, copy, move, rename,
  delete, new folder and name search. It also serves as Save As.
- GitHub Flavored Markdown with footnotes, tables, task lists, alerts,
  definition lists and front matter. Tidy Table aligns pipe tables.
- HTML export with four bundled CSS styles and user styles; preview opens
  the default browser, including on Termux and WSL.
- Crash recovery snapshots, session restore, recent files.
- Plugins via a plugins folder or the `inkmill.plugins` entry point group.
