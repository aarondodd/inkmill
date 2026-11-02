from inkmill import markup


def test_set_heading_adds_replaces_and_removes():
    assert markup.set_heading("Title", 2) == "## Title"
    assert markup.set_heading("### Title", 1) == "# Title"
    assert markup.set_heading("# Title", 0) == "Title"
    assert markup.heading_level("#### x") == 4
    assert markup.heading_level("#nope") == 0


def test_toggle_bullets_on_and_off():
    lines = ["one", "", "two"]
    on = markup.toggle_prefix(lines, "bullet")
    assert on == ["- one", "", "- two"]
    assert markup.toggle_prefix(on, "bullet") == lines


def test_numbered_list_replaces_bullets_and_numbers_in_order():
    assert markup.toggle_prefix(["- a", "- b", "  - c"], "number") == ["1. a", "2. b", "  3. c"]


def test_task_and_quote():
    tasks = markup.toggle_prefix(["buy milk"], "task")
    assert tasks == ["- [ ] buy milk"]
    assert markup.toggle_task_done(tasks[0]) == "- [x] buy milk"
    assert markup.toggle_task_done("- [x] buy milk") == "- [ ] buy milk"
    assert markup.toggle_prefix(["a", "b"], "quote") == ["> a", "> b"]
    assert markup.toggle_prefix(["> a", "> b"], "quote") == ["a", "b"]


def test_next_footnote_number():
    assert markup.next_footnote_number("no notes") == 1
    assert markup.next_footnote_number("a[^1] b[^3]\n\n[^1]: x\n[^3]: y") == 4


def test_make_table_shape():
    table = markup.make_table(2, 3)
    assert len(table) == 5
    assert table[0].count("|") == 3


def test_split_row_respects_escapes_and_code():
    assert markup.split_row("| a | b \\| c | `x|y` |") == ["a", "b \\| c", "`x|y`"]


def test_tidy_table_aligns_and_keeps_alignment_markers():
    rows = ["|Name|Qty|", "|:-|-:|", "|apple|3|", "|kiwi|12|"]
    tidy = markup.tidy_table(rows)
    assert tidy == [
        "| Name  | Qty |",
        "| :---- | --: |",
        "| apple |   3 |",
        "| kiwi  |  12 |",
    ]
    assert len({len(r) for r in tidy}) == 1


def test_table_bounds():
    lines = ["text", "| a |", "|---|", "| 1 |", "", "more"]
    assert markup.table_bounds(lines, 2) == (1, 3)
    assert markup.table_bounds(lines, 0) is None


def test_find_all_case_and_regex():
    assert markup.find_all("Cat cat CAT", "cat") == [(0, 3), (4, 7), (8, 11)]
    assert markup.find_all("Cat cat CAT", "cat", case=True) == [(4, 7)]
    assert markup.find_all("a1 b22", r"\d+", regex=True) == [(1, 2), (4, 6)]
    assert markup.find_all("abc", "") == []
