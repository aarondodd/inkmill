# Inkmill

Terminal word processor for Markdown, built 2026-11-02 at Aaron's request as a
new app inspired by WordGrinder (not a port), with a WordPerfect 5.1 for DOS
look. Private repo https://github.com/aarondodd/inkmill, trunk-based on main.

## Requirements as Aaron stated them

- Python, a modern TUI framework (chose Textual 8).
- Markdown is the primary format; WordGrinder's native format is out of scope.
- Standard top menu bar (File, Edit, ...) that stays hidden and opens on a
  hotkey, for focus-free writing (Esc, F10, Alt+=; Alt+letter opens a menu).
- Default theme WordPerfect 5.2 for DOS style: blue background, white text.
- Built-in file management like WordPerfect, with preview before open and
  multiple open documents (F5 List Files).
- Latest Markdown features: footnotes and tables at minimum.
- No in-app preview; CSS-styled HTML output, and "preview" opens the default
  browser.
- Must run on Windows, Linux and Termux on Android.
- Designed to be extended.

## Layout

See `docs/architecture.md`. Core idea: every action is a `Command` in one
registry; key bindings (priority bindings gated by `check_action` so they go
quiet in dialogs), menus and the Ctrl+P palette are views over it. Plugins
(`register(api)`, plugins folder or `inkmill.plugins` entry point) use the
same registry. One `InkEditor` (TextArea subclass) per document inside a
ContentSwitcher.

## Decisions worth keeping

- All runtime deps are pure Python (textual, markdown-it-py, mdit-py-plugins,
  linkify-it-py, platformdirs, tomli-w) for Termux. tree-sitter highlighting
  is the optional `[syntax]` extra.
- No binding on Ctrl+I/M/H (terminals send Tab/Enter/Backspace). Bold Ctrl+B,
  italic Ctrl+E, footnote Ctrl+F7 (WordPerfect's), go back Alt+B, tidy table
  Ctrl+\.
- Termux preview: loopback HTTP server plus `termux-open-url`, since Android
  browsers cannot read Termux private storage. WSL: `wslview`/`explorer.exe`.
- platformdirs with `appauthor=False` so Windows paths are
  `%LOCALAPPDATA%\inkmill`, not `inkmill\inkmill`.
- Opening a file replaces a lone empty Untitled; File > New never does (a bug
  caught by tests on day one).

## Status

- 0.1.0 committed and pushed 2026-11-02. 52 tests pass (pytest with
  Textual's pilot), green in CI on ubuntu, windows and macos with 3.11 and
  3.13.
- Not yet exercised by a human on Windows Terminal or Termux. L-2026-07-19-001
  applies: verify there before calling it done.

## Ideas not built yet

Spell check, typewriter scrolling, word goal in core (an example plugin
exists), EPUB/ODT/DOCX exporters (plugin-shaped), an outline/heading
navigator, and autosave-to-file as an option beside crash recovery.
