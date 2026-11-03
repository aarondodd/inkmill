"""Spell checking against word lists, with suggestions. No UI code.

The bundled list is US English from SCOWL. Your personal dictionary and any
other ``*.txt`` word lists (one word per line) in the ``dictionaries`` folder
beside settings.toml are added to it, which is how jargon, names and other
languages get in.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

from inkmill.markup import mask_non_prose

WORD = re.compile(r"[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'’]*")
LETTERS = "abcdefghijklmnopqrstuvwxyz'"
BUNDLED = Path(__file__).parent / "dictionaries" / "en_US.txt.gz"


class Checker:
    def __init__(self, extra_dirs: list[Path] | None = None, personal: Path | None = None) -> None:
        self.words: set[str] = set()
        self.lower: set[str] = set()
        self.ignored: set[str] = set()  # "Skip All" for this session
        self.personal = personal
        self._load_bundled()
        for folder in extra_dirs or []:
            if folder.is_dir():
                for path in sorted(folder.glob("*.txt")):
                    self._add_file(path)

    def _add(self, word: str) -> None:
        word = word.strip()
        if word and not word.startswith("#"):
            self.words.add(word)
            self.lower.add(word.lower())

    def _load_bundled(self) -> None:
        with gzip.open(BUNDLED, "rt", encoding="utf-8") as fh:
            for line in fh:
                self._add(line)

    def _add_file(self, path: Path) -> None:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                self._add(line)
        except (OSError, UnicodeDecodeError):
            pass

    def add_to_personal(self, word: str) -> None:
        self._add(word)
        if self.personal is None:
            return
        self.personal.parent.mkdir(parents=True, exist_ok=True)
        with self.personal.open("a", encoding="utf-8") as fh:
            fh.write(word + "\n")

    # -- checking --------------------------------------------------------

    def known(self, word: str) -> bool:
        word = word.replace("’", "'").strip("'")
        if not word or word in self.ignored:
            return True
        if word.endswith("'s"):
            word = word[:-2]
        if not word or any(ch.isdigit() for ch in word):
            return True
        if word in self.words:
            return True
        lower = word.lower()
        # "The" at a sentence start or "NASA"-style capitals: accept when the
        # lowercase form is a word, but "paris" does not pass for "Paris".
        if word[0].isupper() and lower in self.words:
            return True
        if word.isupper() and (lower in self.lower or len(word) <= 5):
            return True
        return False

    def errors(self, text: str) -> list[tuple[int, int, str]]:
        """(start index, end index, word) for every unknown word in ``text``."""
        found = []
        masked = mask_non_prose(text)
        for match in WORD.finditer(masked):
            word = match.group().rstrip("'’")
            if not self.known(word):
                found.append((match.start(), match.start() + len(word), word))
        return found

    # -- suggestions -----------------------------------------------------

    @staticmethod
    def _edits1(word: str) -> set[str]:
        splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
        deletes = [a + b[1:] for a, b in splits if b]
        swaps = [a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1]
        replaces = [a + c + b[1:] for a, b in splits if b for c in LETTERS]
        inserts = [a + c + b for a, b in splits for c in LETTERS]
        return set(deletes + swaps + replaces + inserts)

    def suggest(self, word: str, limit: int = 8) -> list[str]:
        lower = word.lower().replace("’", "'")
        first = self._edits1(lower)
        candidates = [w for w in first if w in self.lower]
        if len(candidates) < limit and len(lower) <= 10:
            second = {e2 for e1 in first for e2 in self._edits1(e1)}
            candidates += [w for w in second - first if w in self.lower]
        # Split run-together words: "alot" -> "a lot".
        for i in range(1, len(lower)):
            left, right = lower[:i], lower[i:]
            if (left in ("a", "i") or len(left) >= 3) and len(right) >= 3 and left in self.lower and right in self.lower:
                candidates.append(f"{left} {right}")
        seen: list[str] = []
        for cand in sorted(candidates, key=lambda c: _rank(lower, c)):
            if cand not in seen:
                seen.append(cand)
            if len(seen) >= limit:
                break
        return [match_case(word, s) for s in seen]


def _distance(a: str, b: str) -> int:
    """Edit distance where swapping two neighbors counts as one edit."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _kind(word: str, cand: str) -> int:
    """How likely this kind of slip is: swapped letters most, a stray space least."""
    if " " in cand:
        return -1 if cand.split(" ")[0] in ("a", "i") else 3
    if len(cand) == len(word):
        diffs = [i for i, (x, y) in enumerate(zip(word, cand)) if x != y]
        if len(diffs) == 2 and diffs[1] == diffs[0] + 1:
            return 0  # transposition
        return 2  # replaced letter
    return 1  # missing or extra letter


def _rank(word: str, cand: str) -> tuple:
    return (1 if " " in cand else _distance(word, cand),
            0 if cand[:1] == word[:1] else 1,
            _kind(word, cand),
            abs(len(cand) - len(word)),
            cand)


def match_case(original: str, replacement: str) -> str:
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement
