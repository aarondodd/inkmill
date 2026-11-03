# Changelog

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
