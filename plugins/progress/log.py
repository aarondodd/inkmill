"""The writing log: words per day, kept in the state folder. No UI code.

A day's count is the net change across every document touched that day:
each document's word count now, minus its count the first time Inkmill saw it
that day. Writing 500 words and cutting 200 counts as 300, which is what a
draft actually gained.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


def today() -> str:
    return date.today().isoformat()


@dataclass
class Sprint:
    started: float
    minutes: int
    start_words: int
    key: str


class WritingLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict = {"days": {}}
        self.dirty = False
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("days"), dict):
                    self.data = loaded
            except (OSError, ValueError):
                pass

    def day(self, when: str | None = None) -> dict:
        return self.data["days"].setdefault(when or today(), {"docs": {}, "sprints": []})

    def see(self, key: str, words: int) -> None:
        """Record a document's current count; the first sighting today is its baseline."""
        docs = self.day()["docs"]
        entry = docs.get(key)
        if entry is None:
            docs[key] = {"start": words, "now": words}
            self.dirty = True
        elif entry["now"] != words:
            entry["now"] = words
            self.dirty = True

    def words(self, when: str | None = None) -> int:
        docs = self.data["days"].get(when or today(), {}).get("docs", {})
        return sum(e["now"] - e["start"] for e in docs.values())

    def add_sprint(self, minutes: int, words: int) -> None:
        self.day()["sprints"].append({"at": datetime.now().strftime("%H:%M"), "minutes": minutes, "words": words})
        self.dirty = True

    def history(self, days: int = 30) -> list[tuple[str, int]]:
        start = date.today()
        return [((start - timedelta(days=i)).isoformat(), self.words((start - timedelta(days=i)).isoformat()))
                for i in range(days - 1, -1, -1)]

    def streak(self, goal: int) -> int:
        """Consecutive days, ending today or yesterday, that met the goal (or wrote anything)."""
        threshold = max(goal, 1)
        day = date.today()
        if self.words(day.isoformat()) < threshold:
            day -= timedelta(days=1)  # today is not over yet
        count = 0
        while self.words(day.isoformat()) >= threshold:
            count += 1
            day -= timedelta(days=1)
        return count

    def save(self, keep_days: int = 400) -> None:
        if not self.dirty:
            return
        days = self.data["days"]
        for old in sorted(days)[:-keep_days]:
            del days[old]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        self.dirty = False


def pace(words: int, target: int, deadline: str) -> str | None:
    """'1,240 words a day to finish by 2027-03-01', or None without a deadline."""
    try:
        end = date.fromisoformat(deadline)
    except (TypeError, ValueError):
        return None
    remaining = target - words
    days = (end - date.today()).days + 1
    if remaining <= 0:
        return "target reached"
    if days <= 0:
        return f"{remaining:,} words past the {deadline} deadline"
    return f"{-(-remaining // days):,} words a day to finish by {deadline}"


def bar_chart(rows: list[tuple[str, int]], goal: int, width: int = 34) -> list[str]:
    peak = max([goal] + [w for _, w in rows] + [1])
    lines = []
    for day, words in rows:
        filled = round(width * max(words, 0) / peak)
        mark = "*" if goal and words >= goal else " "
        lines.append(f"{day[5:]} {mark}{'#' * filled:<{width}} {words:>6,}")
    return lines
