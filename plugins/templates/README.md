# Templates & Journal

Start documents from templates, and keep a daily journal page.

| Command | Key | What it does |
|---------|-----|--------------|
| File > New from Template... | | Pick a template, give it a title, and start writing |
| File > Keep as Template... | | Save the current document as a template of your own |
| File > Today's Journal | Alt+J | Open today's page, creating it if needed, with a time heading for a new entry |

## Bundled templates

Chapter (with Binder's status and synopsis), scene card, character sheet,
location, short story, blog post (front matter for static site
generators), poem, query letter and journal page.

## Your own

Templates are Markdown files. Put them in the `templates` folder beside
settings.toml, or use Keep as Template. One with the same file name as a
bundled template replaces it. These placeholders are filled in:

| Placeholder | Becomes |
|-------------|---------|
| `{{title}}` | the title you type |
| `{{date}}`, `{{time}}`, `{{weekday}}` | today's date, the time, the day name |
| `{{author}}` | your name, asked for once and saved |
| `{{cursor}}` | where the cursor starts |

Two front matter keys describe the template in the list and are removed from
the new document: `template` (its name) and `template_description`.

## Settings

```toml
[plugins.templates]
author = "A. Writer"
journal_dir = "~/Documents/Journal"
journal_name = "%Y-%m-%d.md"     # strftime pattern for each day's file
timestamp_entries = true         # add a "## 14:32" heading for each new entry
```
