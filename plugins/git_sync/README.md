# Git Sync

Commit the document you are writing, with a message, and push or pull its
repository without leaving Inkmill. It needs the `git` command; Inkmill does
not bundle it.

## Which repository

Whichever one contains the current document. Git Sync asks git when you run
a command, so documents from different repositories can be open at the same
time and each one commits to its own. There is no vault to set up.

If a document is not in a repository, the first Git command offers to create
one in its folder.

## Commands

All of these are in the Git menu (Alt+G).

| Command | Key | What it does |
|---------|-----|--------------|
| Commit Document... | Ctrl+F12 | Saves, asks for a message, commits this document only |
| Commit and Push... | | The same, then pushes |
| Pull | | Fast-forwards to the remote; reloads open documents that changed |
| Push | | Pushes; offers to set up tracking for a new branch |
| Sync | | Pull, then push |
| Sync All Tracked Repositories | | Pull and push every repository in your settings |
| Status... | | Branch, tracking, and the changed files |
| History of This Document... | | `git log --follow` for this file |
| Repository Settings... | | Per-repository options, below |

The commit dialog commits just this document by default, leaving anything
else you changed or staged alone. Buttons widen it to every open document in
the repository, or to all changes.

The status line shows `git main *2 ^1`: the branch, the number of changed
files, and commits waiting to be pushed (`v` counts commits to pull, as of
the last fetch).

## Pulling safely

Pull refuses to run while an open document from that repository has unsaved
changes; it offers to save them first. It only fast-forwards by default. If
both you and the remote have new commits, it asks before rebasing your
commits on top. If that conflicts, Git Sync aborts the rebase so everything
is back as it was, and you resolve it from a terminal. Uncommitted changes
in other files are stashed and restored around the pull.

## Credentials

Inside Inkmill git cannot stop to ask for a password, because the terminal
belongs to the editor. Git Sync runs git with prompts turned off and ssh in
batch mode, so a missing credential fails at once with advice instead of
hanging. Set up credentials once from a terminal:

- Windows: Git for Windows includes Git Credential Manager, which opens its
  own sign-in window and works from Inkmill.
- GitHub anywhere: `gh auth login`, then `gh auth setup-git`.
- SSH remotes: load your key into an agent (`ssh-add`). A key with a
  passphrase must already be in the agent.
- Termux: `pkg install git openssh`. Repositories on shared storage may need
  `git config --global --add safe.directory '*'`; Git Sync tells you when.

If git asks who you are, Git Sync asks for your name and email and saves
them for this repository or for all of them.

## Settings

Repository Settings saves options for the current repository. Repositories
you never configure still work with the defaults.

```toml
[plugins.git_sync]
status = true                # show the git segment in the status line
message = "Update {file}"    # default commit message
pull_mode = "ff-only"        # or "rebase", "merge"
push_after_commit = false

[plugins.git_sync.repos."/home/me/writing/novel"]
pull_on_open = true          # pull once per session when a document opens
push_after_commit = true
pull_mode = "rebase"
message = "Writing session {date}"
```

Message templates can use `{file}`, `{title}`, `{date}`, `{time}` and
`{repo}`.
