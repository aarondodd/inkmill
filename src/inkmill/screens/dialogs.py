"""Modal dialogs, styled after WordPerfect's gray boxes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

DIALOG_CSS = """
.im-dialog {
    width: auto;
    max-width: 90%;
    min-width: 40;
    height: auto;
    max-height: 90%;
    background: $im-dialog-bg;
    color: $im-dialog-fg;
    border: double $im-dialog-border;
    padding: 0 1;
}
.im-dialog > .im-title {
    width: 100%;
    content-align: center middle;
    text-style: bold;
    margin-bottom: 1;
}
.im-dialog Label { color: $im-dialog-fg; }
.im-dialog Input {
    background: $im-input-bg;
    color: $im-input-fg;
    border: none;
    height: 1;
    padding: 0 1;
    margin-bottom: 1;
}
.im-dialog Input:focus { border: none; background-tint: transparent; }
.im-dialog Input > .input--cursor { background: $im-input-fg; color: $im-input-bg; }
.im-dialog Input > .input--placeholder { color: $im-input-fg 50%; }
.im-dialog .im-buttons { height: auto; width: 100%; align-horizontal: right; margin-top: 1; }
.im-dialog Button, .im-dialog Button.-textual-compact {
    min-width: 10;
    height: 1;
    margin-left: 1;
    padding: 0 1;
    background: $im-menu-hl-bg;
    color: $im-menu-hl-fg;
    text-style: none;
}
.im-dialog Button:focus { background: $im-input-bg; color: $im-input-fg; text-style: bold; }
.im-dialog Button:hover { background: $im-input-bg; color: $im-input-fg; }
.im-dialog Checkbox { background: transparent; border: none; padding: 0; color: $im-dialog-fg; height: 1; }
.im-dialog Checkbox:focus > .toggle--label { text-style: underline; }
.im-dialog OptionList {
    background: $im-input-bg;
    color: $im-input-fg;
    border: none;
    max-height: 20;
    height: auto;
}
.im-dialog OptionList > .option-list--option-highlighted,
.im-dialog OptionList:focus > .option-list--option-highlighted {
    background: $im-select-bg;
    color: $im-select-fg;
    text-style: none;
}
"""


class Dialog(ModalScreen):
    DEFAULT_CSS = "Dialog { align: center middle; background: $background 30%; }\n" + DIALOG_CSS
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def action_cancel(self) -> None:
        self.dismiss(None)


class InputDialog(Dialog):
    def __init__(self, title: str, prompt: str = "", value: str = "", placeholder: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.prompt = prompt
        self.value = value
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label(self.title_text, classes="im-title")
            if self.prompt:
                yield Label(self.prompt)
            yield Input(self.value, placeholder=self.placeholder, id="value")

    def on_mount(self) -> None:
        self.query_one(Input).styles.width = max(40, len(self.value) + 4)

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


class ConfirmDialog(Dialog):
    """A question with lettered answers, for example Yes / No / Cancel."""

    def __init__(self, title: str, message: str, choices: Iterable[tuple[str, str]] = (("yes", "&Yes"), ("no", "&No"))) -> None:
        super().__init__()
        self.title_text = title
        self.message = message
        self.choices = list(choices)

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label(self.title_text, classes="im-title")
            yield Label(self.message)
            with Horizontal(classes="im-buttons"):
                for value, label in self.choices:
                    yield Button(label.replace("&", ""), id=f"choice-{value}", compact=True)

    def on_mount(self) -> None:
        self.query(Button).first().focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id.removeprefix("choice-"))

    def on_key(self, event: events.Key) -> None:
        if not event.character:
            return
        for value, label in self.choices:
            idx = label.find("&")
            letter = label[idx + 1] if idx >= 0 else label[0]
            if event.character.lower() == letter.lower():
                event.stop()
                self.dismiss(value)
                return


class ChoiceDialog(Dialog):
    """Pick one entry from a list. Returns the entry id."""

    def __init__(self, title: str, items: Iterable[tuple[str, str]], current: str | None = None, prompt: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.items = list(items)
        self.current = current
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label(self.title_text, classes="im-title")
            if self.prompt:
                yield Label(self.prompt)
            options = []
            for item_id, label in self.items:
                marker = "* " if item_id == self.current else "  "
                options.append(Option(Text(marker + label), id=item_id))
            yield OptionList(*options)

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.focus()
        ids = [i for i, _ in self.items]
        if self.current in ids:
            option_list.highlighted = ids.index(self.current)
        elif ids:
            option_list.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)


class TextDialog(Dialog):
    """Scrollable read-only text, used for help and about boxes."""

    DEFAULT_CSS = Dialog.DEFAULT_CSS + """
    TextDialog .im-dialog { width: 76; }
    TextDialog VerticalScroll { height: auto; max-height: 30; }
    """

    BINDINGS = [Binding("escape,enter,q", "cancel", show=False)]

    def __init__(self, title: str, body: str | Text, choices: Iterable[tuple[str, str]] = ()) -> None:
        """``choices`` adds lettered buttons, as in ConfirmDialog; without
        them there is one OK button and the dialog returns None."""
        super().__init__()
        self.title_text = title
        self.body = body
        self.choices = list(choices)

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label(self.title_text, classes="im-title")
            with VerticalScroll():
                yield Static(self.body)
            with Horizontal(classes="im-buttons"):
                if not self.choices:
                    yield Button("OK", id="ok", compact=True)
                for value, label in self.choices:
                    yield Button(label.replace("&", ""), id=f"choice-{value}", compact=True)

    def on_mount(self) -> None:
        if self.choices:
            self.query(Button).first().focus()
        else:
            self.query_one(VerticalScroll).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        self.dismiss(button_id.removeprefix("choice-") if button_id.startswith("choice-") else None)

    def on_key(self, event: events.Key) -> None:
        if not (self.choices and event.character):
            return
        for value, label in self.choices:
            idx = label.find("&")
            letter = label[idx + 1] if idx >= 0 else label[0]
            if event.character.lower() == letter.lower():
                event.stop()
                self.dismiss(value)
                return


@dataclass
class FindRequest:
    action: str  # "next", "previous", "replace", "replace_all"
    needle: str
    replacement: str = ""
    case: bool = False
    regex: bool = False


class FindDialog(Dialog):
    def __init__(self, needle: str = "", replacement: str = "", *, replace: bool = False, case: bool = False, regex: bool = False) -> None:
        super().__init__()
        self.needle = needle
        self.replacement = replacement
        self.replace_mode = replace
        self.case = case
        self.regex = regex

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label("Replace" if self.replace_mode else "Search", classes="im-title")
            yield Label("Find:")
            yield Input(self.needle, id="needle")
            if self.replace_mode:
                yield Label("Replace with:")
                yield Input(self.replacement, id="replacement")
            with Horizontal(classes="im-buttons"):
                yield Checkbox("Match case", self.case, id="case")
                yield Checkbox("Regex", self.regex, id="regex")
            with Horizontal(classes="im-buttons"):
                if self.replace_mode:
                    yield Button("Replace", id="replace", compact=True)
                    yield Button("All", id="replace_all", compact=True)
                yield Button("Prev", id="previous", compact=True)
                yield Button("Next", id="next", compact=True)

    def on_mount(self) -> None:
        for inp in self.query(Input):
            inp.styles.width = 50
        self.query_one("#needle", Input).focus()

    def _request(self, action: str) -> FindRequest:
        replacement = self.query_one("#replacement", Input).value if self.replace_mode else ""
        return FindRequest(
            action=action,
            needle=self.query_one("#needle", Input).value,
            replacement=replacement,
            case=self.query_one("#case", Checkbox).value,
            regex=self.query_one("#regex", Checkbox).value,
        )

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "needle" and self.replace_mode:
            self.query_one("#replacement", Input).focus()
            return
        self.dismiss(self._request("replace" if self.replace_mode else "next"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self._request(event.button.id or "next"))
