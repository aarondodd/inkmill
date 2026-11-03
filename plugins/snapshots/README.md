# Snapshots

Named versions of a document, without git. Take one before a big revision,
compare it with what you have now, and put it back if the revision did not
work.

| Command | Key | What it does |
|---------|-----|--------------|
| File > Take Snapshot... | Ctrl+F5 | Save the document as it is now, with an optional name |
| File > Browse Snapshots... | | List this document's snapshots, newest first |

In the list:

| Key | What it does |
|-----|--------------|
| Enter | Compare with the current text, word by word: removed words struck out, added words underlined |
| R | Restore it; the current text is snapshotted first, and Ctrl+Z undoes the restore |
| O | Open it as a new document |
| N | Rename it |
| D | Delete it |

## Where snapshots are kept

In Inkmill's state folder, one folder per document, so they never end up in
a git repository by accident. Set `location = "beside"` to keep them in a
`.snapshots` folder next to the document instead, which travels with the
project when you copy or sync the folder.

## Settings

```toml
[plugins.snapshots]
location = "state"           # or "beside"
on_save_every_minutes = 0    # take one automatically on save, at most this often; 0 is off
```
