"""Dialogs for Git Sync: commit message and per-repository settings."""

from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label

from inkmill.screens.dialogs import Dialog


@dataclass
class CommitRequest:
    scope: str  # "document", "open", "all"
    message: str
    push: bool


class CommitDialog(Dialog):
    """Dismisses with a :class:`CommitRequest` or None."""

    DEFAULT_CSS = Dialog.DEFAULT_CSS + "CommitDialog Input { width: 60; }"

    def __init__(self, repo: str, document: str, message: str, *, push: bool, others: int, open_count: int) -> None:
        super().__init__()
        self.repo = repo
        self.document = document
        self.message = message
        self.push = push
        self.others = others
        self.open_count = open_count

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label("Commit", classes="im-title")
            yield Label(f"Repository: {self.repo}")
            note = f"{self.others} other changed file(s) in this repository." if self.others else "No other changes in this repository."
            yield Label(note)
            yield Label("Message:")
            yield Input(self.message, id="message")
            yield Checkbox("Push after committing", self.push, id="push")
            with Horizontal(classes="im-buttons"):
                yield Button(f"This document", id="document", compact=True)
                if self.open_count > 1:
                    yield Button(f"Open documents ({self.open_count})", id="open", compact=True)
                if self.others:
                    yield Button("Everything", id="all", compact=True)
                yield Button("Cancel", id="cancel", compact=True)

    def on_mount(self) -> None:
        field = self.query_one("#message", Input)
        field.focus()
        field.cursor_position = len(field.value)

    def _finish(self, scope: str) -> None:
        message = self.query_one("#message", Input).value.strip()
        if not message:
            self.notify("Enter a commit message.", severity="warning")
            return
        self.dismiss(CommitRequest(scope, message, self.query_one("#push", Checkbox).value))

    @on(Input.Submitted)
    def submitted(self, _event: Input.Submitted) -> None:
        self._finish("document")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self._finish(event.button.id or "document")


@dataclass
class RepoOptions:
    pull_on_open: bool
    push_after_commit: bool
    pull_mode: str
    message: str
    forget: bool = False


class RepoSettingsDialog(Dialog):
    """Per-repository preferences. Dismisses with :class:`RepoOptions` or None."""

    DEFAULT_CSS = Dialog.DEFAULT_CSS + "RepoSettingsDialog Input { width: 50; }"

    MODES = ("ff-only", "rebase", "merge")

    def __init__(self, repo: str, options: RepoOptions, tracked: bool) -> None:
        super().__init__()
        self.repo = repo
        self.options = options
        self.tracked = tracked

    def compose(self) -> ComposeResult:
        with Vertical(classes="im-dialog"):
            yield Label("Repository Settings", classes="im-title")
            yield Label(self.repo)
            yield Label("")
            yield Checkbox("Pull when I open a document from it", self.options.pull_on_open, id="pull_on_open")
            yield Checkbox("Push after every commit", self.options.push_after_commit, id="push_after_commit")
            yield Label("Pull mode (ff-only, rebase or merge):")
            yield Input(self.options.pull_mode, id="pull_mode")
            yield Label("Commit message template ({file} {title} {date} {time} {repo}):")
            yield Input(self.options.message, id="message")
            with Horizontal(classes="im-buttons"):
                yield Button("Save", id="save", compact=True)
                if self.tracked:
                    yield Button("Forget", id="forget", compact=True)
                yield Button("Cancel", id="cancel", compact=True)

    def on_mount(self) -> None:
        self.query_one("#pull_on_open", Checkbox).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        mode = self.query_one("#pull_mode", Input).value.strip() or "ff-only"
        if mode not in self.MODES:
            self.notify("Pull mode must be ff-only, rebase or merge.", severity="warning")
            return
        self.dismiss(
            RepoOptions(
                pull_on_open=self.query_one("#pull_on_open", Checkbox).value,
                push_after_commit=self.query_one("#push_after_commit", Checkbox).value,
                pull_mode=mode,
                message=self.query_one("#message", Input).value.strip() or "Update {file}",
                forget=event.button.id == "forget",
            )
        )
