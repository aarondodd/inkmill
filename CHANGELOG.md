# Changelog

## 0.5.1

- Bold and italic text now also get their own colors in the rich view and
  the reading view, so they show in terminals that cannot draw bold or
  italic (bitmap and DOS fonts, or Windows Terminal, which draws bold as a
  brighter color). The WordPerfect theme uses cyan for bold and magenta for
  italic; other themes have their own, and themes without them get colors
  worked out from their palette. View > Emphasis Colors (setting
  `emphasis_colors`) turns the colors off.
- Themes can set `bold` and `italic` colors in their `[ui]` table.
- The reading view shows task boxes as `[x]` and `[ ]`, since check-box
  characters are missing from many terminal fonts.

## 0.5.0

- Rich view (View > Rich View, Alt+F3): Markdown is formatted while you
  write. Bold, italic, bold italic, strikethrough, highlight, headings,
  links, inline and fenced code, quotes, lists, finished tasks, footnotes
  and front matter each get their own look, and the markup characters are
  dimmed but kept, so editing works as in the raw view. Tables line up as
  you type in them, keeping the cursor in its cell. The `rich_view` setting
  remembers the choice. Long documents type faster in the rich view than in
  the raw one, because only the lines on screen are styled.
- Reading view (View > Reading View, Shift+F7): the document fully
  formatted and read-only, opening at the cursor's paragraph. Footnote
  references show as superscripts and task boxes as check boxes; web links
  open in the browser.

## 0.4.2

- The status line keeps the end of a long path visible: leading folders are
  dropped first (`.../chapters/the-crossing.md *`), and a long file name is
  cut from the left, so the name and the unsaved marker always show.
- Typing that wraps onto a new last line no longer leaves the cursor hidden
  under the status line until the next key.
- Snapshots 1.0.1: two snapshots taken in quick succession on Windows
  could list oldest first; they now list in the order taken.

## 0.4.1

- Update checking: once a day Inkmill says when a newer version is out, and
  Help > Check for Updates shows what is new and installs it. Inkmill works
  out how it was installed (pipx, pip in a virtual environment or the user
  folder, a source folder) and runs the matching command, checks that the
  new version is installed, and offers to restart into it. On Windows the
  update runs in a new window after Inkmill closes. Where Inkmill cannot run
  the command (a system Python, no permission, no pip), it shows the command
  and why, and can copy it.
- `inkmill --check-update` and `inkmill --update` on the command line.
- `[updates]` settings: `check` ("daily", "startup", "off"),
  `auto_install` and `url`.
- Help > About shows how Inkmill was installed.

## 0.4.0

- AI Assistant 1.1: a Claude Code provider that sends requests through your
  installed, logged-in `claude` program, so they count against your Claude
  plan rather than API billing. Each project (a binder, or a document's
  folder) keeps one conversation that later requests continue, and Claude
  may read the project's files itself (read-only, confined to the project)
  instead of being sent them; unsaved changes are handed over as a copy.
  New Conversation and Continue in Claude Code manage the conversation.
- A story bible per project (`Story Bible.md`), read with every AI request
  by every provider and checked by Continuity Check; B in the reply panel
  adds a reply to it.
- The AI consent dialog wraps its text instead of cutting it off.

## 0.3.0

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
