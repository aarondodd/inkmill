# Comments & Track Changes

Comments and suggested edits kept in the text itself as
[CriticMarkup](https://fletcher.github.io/MultiMarkdown-6/syntax/critic.html),
so they survive any tool, any sync and any git merge, and an editor without
Inkmill can still read them.

| Markup | Meaning |
|--------|---------|
| `{>>A comment<<}` | A comment |
| `{==this passage==}{>>a comment about it<<}` | A comment on a passage |
| `{++added++}` | Suggested insertion |
| `{--removed--}` | Suggested deletion |
| `{~~old~>new~~}` | Suggested replacement |

All commands are in the Review menu (Alt+R):

| Command | Key | What it does |
|---------|-----|--------------|
| Add Comment... | Alt+C | Comment on the selection, or at the cursor |
| Suggest Insertion... | | Propose text to add after the cursor |
| Suggest Deletion | | Mark the selection for deletion |
| Suggest Replacement... | | Propose new wording for the selection |
| Review Changes | | Every comment and suggestion in the side panel |
| Accept All / Reject All | | Resolve everything at once; Ctrl+Z undoes it |

In the review list, Enter goes to an item, A accepts it and R rejects it.
Accepting a comment removes it. Suggestions are colored in the text:
additions underlined, deletions struck through, comments in the heading
color.

## Export

HTML export and preview show the marks by default: insertions and deletions
highlighted, comments as small notes. Change `export` to get a clean copy:

```toml
[plugins.comments]
export = "show"     # or "final" (every suggestion accepted) or "original" (every one rejected)
```

Export via Pandoc always uses the final text.
