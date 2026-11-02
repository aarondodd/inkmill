"""Open documents and the list that holds them."""

from __future__ import annotations

import hashlib
import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

from .formats import DocumentFormat

_ids = itertools.count(1)

# Markdown punctuation that should not count as words.
_MARKUP = re.compile(r"(^|\s)(#{1,6}|[-*+]|\d+[.)]|>+|\|)(?=\s)|[`*_~|]|\[\^?|\]\([^)]*\)|\]")
_WORD = re.compile(r"[\w'-]+", re.UNICODE)


def count_words(text: str) -> int:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            text = text[end + 4 :]
    return len(_WORD.findall(_MARKUP.sub(" ", text)))


@dataclass
class Document:
    format: DocumentFormat
    path: Path | None = None
    text: str = ""
    saved_text: str = ""
    id: int = field(default_factory=lambda: next(_ids))
    untitled_number: int = 0

    @property
    def dirty(self) -> bool:
        return self.text != self.saved_text

    @property
    def title(self) -> str:
        if self.path is not None:
            return self.path.name
        return f"Untitled {self.untitled_number}" if self.untitled_number > 1 else "Untitled"

    @property
    def display_path(self) -> str:
        if self.path is None:
            return self.title
        try:
            return "~/" + self.path.resolve().relative_to(Path.home()).as_posix()
        except ValueError:
            return str(self.path)

    @property
    def recovery_key(self) -> str:
        source = str(self.path.resolve()) if self.path else f"untitled-{self.id}"
        return hashlib.sha1(source.encode()).hexdigest()[:16]

    @classmethod
    def from_file(cls, path: Path, fmt: DocumentFormat) -> "Document":
        text = fmt.load(path) if path.exists() else ""
        return cls(format=fmt, path=path, text=text, saved_text=text)

    def save(self, path: Path | None = None) -> Path:
        target = path or self.path
        if target is None:
            raise ValueError("document has no path")
        self.format.save(target, self.text)
        self.path = target
        self.saved_text = self.text
        return target

    def word_count(self) -> int:
        return count_words(self.text)


class DocumentList:
    """Ordered open documents plus which one is active."""

    def __init__(self) -> None:
        self.docs: list[Document] = []
        self.active_index: int = -1

    def __len__(self) -> int:
        return len(self.docs)

    def __iter__(self):
        return iter(self.docs)

    @property
    def active(self) -> Document | None:
        if 0 <= self.active_index < len(self.docs):
            return self.docs[self.active_index]
        return None

    def number_of(self, doc: Document) -> int:
        return self.docs.index(doc) + 1

    def next_untitled_number(self) -> int:
        used = {d.untitled_number for d in self.docs if d.path is None}
        n = 1
        while n in used:
            n += 1
        return n

    def add(self, doc: Document) -> Document:
        if doc.path is None and not doc.untitled_number:
            doc.untitled_number = self.next_untitled_number()
        self.docs.append(doc)
        self.active_index = len(self.docs) - 1
        return doc

    def find_path(self, path: Path) -> Document | None:
        target = path.resolve()
        for doc in self.docs:
            if doc.path is not None and doc.path.resolve() == target:
                return doc
        return None

    def activate(self, doc: Document) -> None:
        self.active_index = self.docs.index(doc)

    def cycle(self, step: int) -> Document | None:
        if not self.docs:
            return None
        self.active_index = (self.active_index + step) % len(self.docs)
        return self.active

    def remove(self, doc: Document) -> None:
        idx = self.docs.index(doc)
        self.docs.pop(idx)
        if not self.docs:
            self.active_index = -1
        elif self.active_index >= idx:
            self.active_index = max(0, self.active_index - 1)

    def replace_if_pristine(self, doc: Document) -> Document | None:
        """Opening a file replaces a lone, empty, untitled document.

        Returns the dropped document. A new untitled document never replaces
        another, so File > New always adds one.
        """
        if doc.path is not None and len(self.docs) == 1:
            only = self.docs[0]
            if only.path is None and not only.text and doc is not only:
                self.remove(only)
                return only
        return None
