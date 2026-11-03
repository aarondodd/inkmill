"""Prose Check: style findings in the side panel, with readability numbers.

Built-in checks look for passive voice, adverbs, filler and wordy phrases,
cliches, repeated words, weak openers, long sentences and repeated sentence
starts. If Vale is installed and finds a configuration (a .vale.ini in the
document's folder or above, or the ``vale_config`` setting), its findings are
added too. Enter in the list selects the passage; the list and the
highlights follow your edits while the panel is open.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from .rules import RULE_NAMES, Finding, check, readability

OWNER = "prose"
HINT = "Enter select  Ctrl+T text  Esc close"


class FindingList(OptionList):
    def __init__(self, jump) -> None:
        super().__init__()
        self.jump = jump

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id:
            self.jump(int(event.option.id))


def find_vale_config(start: Path) -> Path | None:
    for folder in [start, *start.parents]:
        for name in (".vale.ini", "_vale.ini", "vale.ini"):
            if (folder / name).is_file():
                return folder / name
    return None


def run_vale(text: str, config: Path, suffix: str = ".md") -> list[Finding]:
    """Vale's alerts for ``text``, as findings with character offsets."""
    exe = shutil.which("vale")
    if exe is None:
        return []
    try:
        proc = subprocess.run(
            [exe, f"--config={config}", f"--ext={suffix}", "--output=JSON"],
            input=text.encode("utf-8"), capture_output=True, timeout=60, stdin=None,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    try:
        data = json.loads(proc.stdout.decode("utf-8") or "{}")
    except ValueError:
        return []
    starts = [0]
    for line in text.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    found = []
    for alerts in data.values() if isinstance(data, dict) else []:
        for alert in alerts:
            line = int(alert.get("Line", 1)) - 1
            span = alert.get("Span") or [1, 1]
            if not 0 <= line < len(starts) - 1:
                continue
            a = starts[line] + int(span[0]) - 1
            b = starts[line] + int(span[1])
            found.append(Finding(a, b, "vale", f"{alert.get('Check', 'Vale')}: {alert.get('Message', '')}"))
    return found


def register(api):
    app = api.app
    state: dict = {"widget": None, "findings": [], "doc": None}

    api.add_menu("tools", "&Tools")
    api.decoration_style("prose.finding", lambda v: Style(color=v.get("im-heading"), underline=True))

    def has_doc(_app) -> bool:
        return app.active_editor is not None

    def enabled_rules() -> set[str] | None:
        rules = api.settings.get("rules")
        return set(rules) if isinstance(rules, list) else None

    def vale_config(doc) -> Path | None:
        if not api.settings.get("use_vale", True) or shutil.which("vale") is None:
            return None
        configured = api.settings.get("vale_config")
        if configured:
            path = Path(str(configured)).expanduser()
            return path if path.is_file() else None
        return find_vale_config(doc.path.parent) if doc.path is not None else None

    def analyze(text: str, config: Path | None) -> list[Finding]:
        found = check(text, rules=enabled_rules(), long_sentence=int(api.settings.get("long_sentence", 35)))
        if config is not None:
            found += run_vale(text, config)
        return sorted(found, key=lambda f: f.start)

    def jump(index: int) -> None:
        editor = app.active_editor
        findings = state["findings"]
        if editor is None or not 0 <= index < len(findings):
            return
        finding = findings[index]
        editor.select_range(editor.location_of(finding.start), editor.location_of(finding.end))
        editor.focus()

    async def refresh() -> None:
        editor = app.active_editor
        widget: FindingList | None = state["widget"]
        if editor is None:
            return
        if widget is None or not api.owns_panel:
            editor.clear_decorations(OWNER)
            return
        text = editor.text
        doc = editor.doc
        findings = await api.run_in_thread(analyze, text, vale_config(doc))
        stats = await api.run_in_thread(readability, text)
        if editor.text != text:
            return
        state["findings"] = findings
        editor.set_decorations(OWNER, [(editor.location_of(f.start), editor.location_of(f.end), "prose.finding") for f in findings])
        options = [Option(summary(stats), disabled=True)]
        for i, f in enumerate(findings):
            row, col = editor.location_of(f.start)
            snippet = text[f.start:f.end].replace("\n", " ")
            if len(snippet) > 28:
                snippet = snippet[:25] + "..."
            line = Text(f"{row + 1:>4}  ", style="dim")
            line.append(snippet, style="bold")
            line.append(f"\n      {f.message}")
            options.append(Option(line, id=str(i)))
        if len(options) == 1:
            options.append(Option("Nothing to flag.", disabled=True))
        keep = widget.highlighted
        widget.clear_options()
        widget.add_options(options)
        if keep is not None and keep < len(options) and not options[keep].disabled:
            widget.highlighted = keep
        elif len(options) > 1 and not options[1].disabled:
            widget.highlighted = 1
        app.panel.set_title(f"Prose: {len(findings)} finding(s)")

    def summary(stats: dict) -> Text:
        text = Text()
        text.append(f"{stats['words']:,} words, {stats['sentences']:,} sentences, "
                    f"{stats['avg_sentence']:.1f} words a sentence\n", style="italic")
        text.append(f"Reading ease {stats['ease']:.0f}, grade {stats['grade']:.1f}, "
                    f"{stats['reading_minutes']:.0f} min to read", style="italic")
        return text

    @api.command("prose.check", "Prose &Check", menu="tools", separator=True, enabled=has_doc,
                 description="Style findings and readability in the side panel")
    async def show(app):
        if api.owns_panel:
            api.hide_panel()
            app.active_editor.clear_decorations(OWNER)
            return
        widget = FindingList(jump)
        state["widget"] = widget
        await api.show_panel(widget, "Prose", HINT)
        await refresh()

    @api.on("document_changed")
    async def changed(app, doc):
        await refresh()

    @api.on("document_activated")
    async def activated(app, doc):
        await refresh()

    @api.on("panel_closed")
    def closed(app, owner):
        if owner == api.plugin_name:
            for editor in app.query("InkEditor"):
                editor.clear_decorations(OWNER)

    @api.command("prose.rules", "Prose Check &Options...", menu="tools",
                 description="Choose which checks run")
    async def choose_rules(app):
        from inkmill.screens.dialogs import ChoiceDialog

        current = enabled_rules() or set(RULE_NAMES)
        while True:
            items = [(rule, ("[x] " if rule in current else "[ ] ") + name) for rule, name in RULE_NAMES.items()]
            items.append(("done", "Done"))
            choice = await app.push_screen_wait(ChoiceDialog("Prose Check Rules", items, prompt="Enter toggles a check."))
            if choice in (None, "done"):
                break
            current ^= {choice}
        api.settings["rules"] = sorted(current)
        api.save_settings()
        await refresh()
