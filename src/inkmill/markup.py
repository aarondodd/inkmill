"""Pure Markdown editing helpers.

Nothing here knows about widgets: each function takes lines or strings and
returns new ones, which keeps the editing rules easy to test and reuse.
"""

from __future__ import annotations

import re
import unicodedata

HEADING = re.compile(r"^(\s{0,3})(#{1,6})(\s+|$)")
BULLET = re.compile(r"^(\s*)([-*+])\s+(\[[ xX]\]\s+)?")
NUMBERED = re.compile(r"^(\s*)(\d+)[.)]\s+")
QUOTE = re.compile(r"^(\s*)>\s?")
TASK = re.compile(r"^(\s*)[-*+]\s+\[[ xX]\]\s+")
FOOTNOTE_LABEL = re.compile(r"\[\^(\d+)\]")
FOOTNOTE_DEF = re.compile(r"^\[\^[^\]]+\]:")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_CELL = re.compile(r"^\s*:?-{1,}:?\s*$")


def set_heading(line: str, level: int) -> str:
    """Make ``line`` a heading of ``level`` (0 makes it a plain paragraph)."""
    body = HEADING.sub(r"\1", line, count=1).lstrip()
    if level <= 0:
        return body
    return f"{'#' * min(level, 6)} {body}"


def heading_level(line: str) -> int:
    match = HEADING.match(line)
    return len(match.group(2)) if match else 0


def _strip_block_prefix(line: str) -> str:
    for pattern in (TASK, BULLET, NUMBERED):
        match = pattern.match(line)
        if match:
            return match.group(1) + line[match.end() :]
    return line


def toggle_prefix(lines: list[str], kind: str) -> list[str]:
    """Toggle a block prefix on every line: bullet, number, task or quote.

    If every non-blank line already has the prefix it is removed; otherwise it
    is applied, replacing any other list marker.
    """
    checks = {
        "bullet": lambda s: bool(BULLET.match(s)) and not TASK.match(s),
        "number": lambda s: bool(NUMBERED.match(s)),
        "task": lambda s: bool(TASK.match(s)),
        "quote": lambda s: bool(QUOTE.match(s)),
    }
    if kind not in checks:
        raise ValueError(kind)
    content = [ln for ln in lines if ln.strip()]
    remove = bool(content) and all(checks[kind](ln) for ln in content)
    out: list[str] = []
    n = 0
    for line in lines:
        if not line.strip():
            out.append(line)
            continue
        if kind == "quote":
            out.append(QUOTE.sub(r"\1", line, count=1) if remove else f"> {line}")
            continue
        base = _strip_block_prefix(line)
        if remove:
            out.append(base)
            continue
        indent = base[: len(base) - len(base.lstrip())]
        text = base.lstrip()
        n += 1
        prefix = {"bullet": "- ", "number": f"{n}. ", "task": "- [ ] "}[kind]
        out.append(f"{indent}{prefix}{text}")
    return out


def toggle_task_done(line: str) -> str:
    match = re.match(r"^(\s*[-*+]\s+\[)([ xX])(\].*)$", line)
    if not match:
        return line
    mark = " " if match.group(2).lower() == "x" else "x"
    return match.group(1) + mark + match.group(3)


def next_footnote_number(text: str) -> int:
    numbers = [int(n) for n in FOOTNOTE_LABEL.findall(text)]
    return max(numbers, default=0) + 1


def make_table(columns: int, rows: int) -> list[str]:
    columns = max(1, columns)
    rows = max(1, rows)
    header = "| " + " | ".join(f"Column {i + 1}" for i in range(columns)) + " |"
    sep = "|" + "|".join("-" * (len(f"Column {i + 1}") + 2) for i in range(columns)) + "|"
    blank = "| " + " | ".join(" " * len(f"Column {i + 1}") for i in range(columns)) + " |"
    return [header, sep] + [blank] * rows


def _display_width(text: str) -> int:
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def split_row(line: str) -> list[str]:
    """Split a pipe-table row into cells, honoring escaped pipes and code spans."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells: list[str] = []
    current: list[str] = []
    in_code = False
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            current.append(s[i : i + 2])
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    cells.append("".join(current).strip())
    return cells


def table_bounds(lines: list[str], row: int) -> tuple[int, int] | None:
    """Return (first, last) line indexes of the pipe table containing ``row``."""
    if not (0 <= row < len(lines)) or not TABLE_ROW.match(lines[row]):
        return None
    first = row
    while first > 0 and TABLE_ROW.match(lines[first - 1]):
        first -= 1
    last = row
    while last + 1 < len(lines) and TABLE_ROW.match(lines[last + 1]):
        last += 1
    return first, last


def tidy_table(lines: list[str]) -> list[str]:
    """Pad every cell so the pipes line up, keeping column alignment markers."""
    rows = [split_row(line) for line in lines]
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    sep_index = next(
        (i for i, r in enumerate(rows) if all(TABLE_SEP_CELL.match(c) for c in r if c) and any(r)), None
    )
    aligns = ["left"] * ncols
    if sep_index is not None:
        for c, cell in enumerate(rows[sep_index]):
            cell = cell.strip()
            if cell.startswith(":") and cell.endswith(":"):
                aligns[c] = "center"
            elif cell.endswith(":"):
                aligns[c] = "right"
            elif cell.startswith(":"):
                aligns[c] = "leftmark"
    widths = [3] * ncols
    for i, r in enumerate(rows):
        if i == sep_index:
            continue
        for c, cell in enumerate(r):
            widths[c] = max(widths[c], _display_width(cell))
    out = []
    for i, r in enumerate(rows):
        if i == sep_index:
            cells = []
            for c in range(ncols):
                w = widths[c]
                a = aligns[c]
                if a == "center":
                    cells.append(":" + "-" * (w - 2) + ":")
                elif a == "right":
                    cells.append("-" * (w - 1) + ":")
                elif a == "leftmark":
                    cells.append(":" + "-" * (w - 1))
                else:
                    cells.append("-" * w)
            out.append("| " + " | ".join(cells) + " |")
            continue
        cells = []
        for c, cell in enumerate(r):
            pad = widths[c] - _display_width(cell)
            if aligns[c] == "right":
                cells.append(" " * pad + cell)
            elif aligns[c] == "center":
                left = pad // 2
                cells.append(" " * left + cell + " " * (pad - left))
            else:
                cells.append(cell + " " * pad)
        out.append("| " + " | ".join(cells) + " |")
    return out


def find_all(text: str, needle: str, *, case: bool = False, regex: bool = False) -> list[tuple[int, int]]:
    """Return (start, end) offsets of every match."""
    if not needle:
        return []
    flags = 0 if case else re.IGNORECASE
    pattern = re.compile(needle if regex else re.escape(needle), flags)
    return [(m.start(), m.end()) for m in pattern.finditer(text) if m.end() > m.start()]
