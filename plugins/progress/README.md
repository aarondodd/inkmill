# Progress

Words written each day against a goal, your streak, timed writing sprints,
and how fast you need to go to finish a project on time. Replaces the Word
Goal example plugin.

| Command | Key | What it does |
|---------|-----|--------------|
| Tools > Progress... | Ctrl+F8 | Today, your streak, today's sprints, the project, and the last 30 days as a bar chart |
| Tools > Set Daily Goal... | | Words a day; the status line shows `Today 812/1,000` |
| Tools > Start Sprint... | | A timed session; the status line counts down and shows words gained |
| Tools > Stop Sprint | | End a sprint early |
| Tools > Project Target... | | A total word target and a deadline, for the binder or this document |

## How words are counted

A day's count is the net change in every document you worked on that day:
its word count now, minus its count the first time Inkmill saw it that day.
Writing 500 words and cutting 200 counts as 300. Opening a finished draft
counts as nothing. The log lives in Inkmill's state folder
(`progress.json`) and keeps about a year.

With the Binder plugin, Project Target applies to the whole binder and the
pace is computed from every chapter. Without it, the target and deadline go
in the document's own front matter (`target`, `deadline`).

## Settings

```toml
[plugins.progress]
daily_goal = 1000
sprint_minutes = 25
status = true        # show today's count or the sprint in the status line
```
