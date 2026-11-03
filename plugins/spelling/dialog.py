"""The spell check box, after WordPerfect's: one word at a time, in context."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from inkmill.screens.dialogs import Dialog


@dataclass
class SpellAnswer:
    action: str  # "replace", "skip", "ignore", "add", "stop"
    text: str = ""


class SpellDialog(Dialog):
    """Dismisses with a :class:`SpellAnswer`."""

    DEFAULT_CSS = Dialog.DEFAULT_CSS + """
    SpellDialog { align: center bottom; }
    SpellDialog .im-dialog { width: 72; margin-bottom: 2; }
    SpellDialog #sp-context { margin-bottom: 1; }
    SpellDialog OptionList { max-height: 8; }
    SpellDialog Input { width: 100%; }
    """

    def __init__(self, word: str, context: str, offset: int, suggestions: list[str], progress: str) -> None:
        super().__init__()
        self.word = word
        self.context = context
        self.word_offset = offset
        self.suggestions = suggestions
        self.progress = progress

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label(f"Spelling: not found  {self.progress}", classes="im-title")
            text = Text(self.context)
            text.stylize("bold reverse", self.word_offset, self.word_offset + len(self.word))
            yield Static(text, id="sp-context")
            if self.suggestions:
                yield OptionList(*[Option(s, id=f"s{i}") for i, s in enumerate(self.suggestions)], id="sp-list")
            else:
                yield Label("No suggestions.")
            yield Label("Or type the word:")
            yield Input(self.word, id="sp-edit")
            with Horizontal(classes="im-buttons"):
                yield Button("Skip", id="skip", compact=True)
                yield Button("Skip All", id="ignore", compact=True)
                yield Button("Add", id="add", compact=True)
                yield Button("Stop", id="stop", compact=True)

    def on_mount(self) -> None:
        target = self.query("#sp-list")
        (target.first() if target else self.query_one(Input)).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(SpellAnswer("replace", self.suggestions[int(event.option.id[1:])]))

    @on(Input.Submitted)
    def typed(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        self.dismiss(SpellAnswer("replace", value) if value and value != self.word else SpellAnswer("skip"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(SpellAnswer(event.button.id or "skip"))

    def on_key(self, event: events.Key) -> None:
        if isinstance(self.focused, Input):
            return
        keys = {"s": "skip", "i": "ignore", "a": "add", "1": "skip", "2": "ignore", "3": "add"}
        if event.character and event.character.lower() in keys:
            event.stop()
            self.dismiss(SpellAnswer(keys[event.character.lower()]))
        elif event.character and event.character.lower() == "e":
            event.stop()
            self.query_one(Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(SpellAnswer("stop"))
