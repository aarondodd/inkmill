# AI Assistant

Help from a language model when you ask for it, and only then. Replies
appear in the side panel and never change your text on their own.

![AI feedback](https://raw.githubusercontent.com/aarondodd/inkmill/main/docs/screenshots/ai.png)

All commands are in the AI menu (Alt+A):

| Command | What it does |
|---------|--------------|
| Ask... | Any question about the selection, or about the whole document |
| Feedback | An editor's notes on the selection or the chapter: what works, and the three changes that would help most |
| Rewrite Selection... | Three versions of the selection (tighter, warmer, simpler: you say how); press 1, 2 or 3 to use one |
| Summarize | A short summary and the key points |
| Write Synopsis | One or two sentences for the chapter, which you can edit before it is saved to front matter (and shown in Binder's outline) |
| Continuity Check | Reads the whole binder and its research notes and lists names, dates, places and facts that disagree, quoting both passages |
| Story Bible | Opens the project's story bible, creating it if needed (see below) |
| Update Story Bible from Conversation... | Suggests bible entries for what the conversation settled; you pick which to add (see below) |
| New Conversation | Claude Code only: start a fresh conversation for this project |
| Conversation History... | The earlier requests and replies in this project's conversation, to pick one and read it in the reply panel (see below) |
| Continue in Claude Code... | Claude Code only: the command that opens this project's conversation in Claude Code itself |
| Save Conversation as Research Note... | Claude Code only: writes this project's conversation into a note in the binder's research (see below) |
| Show Saved Conversation... | With a saved conversation note open: page through its turns in the reply panel, like Conversation History |
| Set API Key... | Store your key (API providers) |
| AI Settings... | Choose the provider, model and server or program |

In the reply panel: I inserts the reply at the cursor, R replaces the text
you selected, 1 to 3 pick a rewrite, Q asks a follow-up question in the same
conversation, B adds the reply to the story bible, C copies the reply, and
Esc closes the panel (and stops a reply still arriving).

### Earlier turns

The reply panel shows your request above the reply: the command, the
document it was made from, and your question or the passage it was about
(long passages are cut to their first lines). Left and Right, or `[` and
`]`, page back and forward through the earlier turns of the conversation,
and the panel's title shows where you are, as in "AI: Feedback (turn 3 of
7)". L lists every turn with its command, its document and a short
description; type to search the requests and replies, and Enter shows the
turn. AI > Conversation History opens the same list without asking
anything new.

On an earlier turn, I, C and B use the reply you are looking at. R and 1
to 3 work only on the newest reply, since they change the text you had
selected when you asked. Q always continues from the end of the
conversation.

Inkmill keeps every turn in the project's folder, in
`.inkmill/ai-conversation.jsonl`, whichever provider answered. That record
lasts: it survives quitting Inkmill, Claude Code's clean-up of old
conversations, and starting a new conversation (New Conversation starts
Claude afresh, but Conversation History still lists the earlier turns). It
travels with the folder when you move, copy or sync it. With Claude Code,
turns that Claude Code has and the record lacks (requests made before
Inkmill 0.5.4, or typed in Claude Code itself) are copied in whenever you
open the history or ask something.

To page through a conversation you saved as a note, open the note and
choose AI > Show Saved Conversation.

To copy earlier conversations into a project's record without opening
Inkmill, run:

```
inkmill --import-conversation /path/to/project
inkmill --import-conversation /path/to/project --from all
inkmill --import-conversation /path/to/project --from research/ai-conversation-2026-11-12.md
```

The first copies the Claude Code conversation Inkmill uses for that
folder; `--from all` copies every Claude Code conversation started in it,
including ones you had in a terminal; `--from` with a saved conversation
note copies the note's turns, and with a Claude Code session id or
`.jsonl` file, that conversation. Running it again adds nothing new.

Set `keep_history = false` to keep no record in the project folder. Then
Claude Code's turns come only from its own files, and the other providers'
turns last only until Inkmill quits.

## Providers

| Provider | Needs | Billed to |
|----------|-------|-----------|
| Claude Code | The `claude` program installed and logged in | Your Claude plan (Pro, Max, Team) |
| Claude (Anthropic), the default, model `claude-sonnet-5-5` | An API key from console.anthropic.com | Your API account, per token |
| Ollama, on this computer | [Ollama](https://ollama.com) running with a model pulled (`ollama pull llama3.1`); nothing leaves your machine and no key is needed | Nobody |
| OpenAI-compatible server | Its address, a model name and, usually, a key; works with LM Studio, llama.cpp's server and hosted services that speak the same API | That service |

Choose one with AI > AI Settings.

## Using Claude Code (your Claude plan)

If you already use Claude Code, the AI Assistant can send its requests
through it. Requests then count against your Claude plan's usage, like
anything else you do in Claude Code, instead of being billed per token to an
API account. Inkmill never sees your login: it starts your own `claude`
program, which uses the account you logged in with.

Two other things change with Claude Code. Each project keeps one
conversation, so Claude remembers what you asked earlier in a long writing
session, even after you quit Inkmill. And Claude can read the project's
files itself instead of being sent them.

### Set it up

1. Install Claude Code. See [the setup guide](https://code.claude.com/docs/en/setup):

   | System | Command |
   |--------|---------|
   | Linux, macOS, WSL | `curl -fsSL https://claude.ai/install.sh \| bash` |
   | macOS with Homebrew | `brew install --cask claude-code` |
   | Windows (PowerShell) | `irm https://claude.ai/install.ps1 \| iex` |
   | Termux on Android | See [Termux](#termux) below |

2. Run `claude` once in a terminal and log in with your Claude account
   (`/login` if it does not ask). Then quit it with `/exit`.
3. Check that it answers without a terminal:
   `claude -p "Say hello"` should print a greeting. If it prints "Not
   logged in", repeat step 2.
4. In Inkmill, open AI > AI Settings, pick "Claude Code, your Claude plan",
   and answer three questions:
   - Model: `sonnet`, `opus`, `haiku` or a full model name. Leave it empty
     to use whatever Claude Code itself defaults to on your plan. Sonnet is a
     good balance for writing help; Opus is slower and uses your plan's
     limits faster.
   - Program: `claude` if it is on your PATH. Otherwise the full path, or a
     whole command such as `~/bin/claude-wrapper`.
   - Project files: whether Claude may read the project's files (the
     recommended choice; see below), or only gets the text each command names.
5. Run any AI command. The first time, Inkmill asks before sending anything.

View > Plugins shows whether the `claude` program was found, with the
install command for your system.

### One conversation per project

A project is a binder (all of its chapters and research), or, for a
document that is not in a binder, the folder the document is in. Unsaved
new documents share one project.

Every AI command in a project continues the same Claude Code conversation:
the panel title shows the turn, as in "AI: Feedback (conversation turn 7)".
So you can ask for feedback on chapter 3, rewrite a paragraph, and later
ask "is this better than what you saw before?" and Claude knows what you
mean. The conversation survives quitting Inkmill and restarting your
computer, because Claude Code keeps it on disk.

When Claude Code no longer has a project's conversation (it cleaned it
up, or the folder was moved, renamed or synced from another computer),
the next request starts a new one and tells Claude where the earlier
turns are: Inkmill writes them to `.inkmill/earlier-conversation.md` for
Claude to read when a request depends on them (with project files off,
they go with the request instead). Claude then works from that copy of the
earlier conversation rather than its own memory of it, and the history
still lists every turn.

Use AI > New Conversation when you start on something unrelated, or when
replies start missing earlier details. Very long conversations are
summarized by Claude Code to make room ("compacted"), and a summary keeps
less detail than the original. That is what the story bible is for.

### From an idea to a binder

A document that is not in a binder shares its conversation with every
other loose document in the same folder. So give each idea its own folder
from the start (`ideas/lighthouse/lighthouse.md`, not a single `ideas/`
folder of drafts), and its conversation stays its own.

When the idea grows into a project, keep the conversation by putting the
binder in that same folder:

1. Open the idea's document.
2. Choose Binder > New Binder Document... and accept the folder it offers
   (the document's own). The document becomes the binder's first entry.
3. Carry on. The binder's folder is the folder the conversation already
   belongs to, so the next AI request continues it, and Conversation
   History shows every earlier turn.

New chapters can go in a subfolder (`chapters/`): the project is the
binder's folder, so they share the conversation too.

Moving or renaming the idea's whole folder keeps its conversation: the
record in `.inkmill` moves with it, and the first request from the new
place gives Claude the earlier turns (see One conversation per project).

To add the idea to a binder that already exists in another folder, the
conversation cannot come along: the binder's folder has its own. Keep the
idea's conversation as a note instead:

1. With the document still outside the binder, choose AI > Save
   Conversation as Research Note.... The note goes in a `research` folder
   beside the document.
2. If you want the file beside the binder's chapters, move it there
   first with List Files (F5), which updates its links.
3. With the idea's document open, choose Binder > Link Document..., then
   "Binder (parent document)", and pick the binder's file. Answer Yes when
   asked to link back, so the document joins the binder's contents.
4. Still in that document, choose Binder > Add Research... and pick the
   saved note. It is now listed with the binder's research.
5. When you next ask something, name the note (for example "first read
   the research note ai-conversation-2026-11-12.md"). With project files
   on, Claude finds and reads it.
6. Optionally, run `inkmill --import-conversation /path/to/binder-folder
   --from /path/to/the-note.md` to list the note's turns in the binder's
   Conversation History.

The old conversation also stays in Claude Code: run `claude --resume` in a
terminal in the idea's old folder to find it. That lasts until Claude Code
cleans it up; by default it removes conversations unused for about 30
days, and its `cleanupPeriodDays` setting changes that. The research note
is the copy that lasts.

Write Synopsis is the one command kept out of the conversation, so
generating synopses for twenty chapters does not crowd it.

AI > Continue in Claude Code shows the two commands that open the same
conversation in Claude Code in a terminal (and copies them):

```
cd "/path/to/your/book"
claude --resume 3f6c...
```

Anything you discuss there is part of the conversation the next time you ask
from Inkmill. Claude Code in a terminal has its usual tools and settings;
inside Inkmill it has far fewer (see Privacy).

AI > Save Conversation as Research Note writes the whole conversation so
far into a Markdown note, so you can keep it with the book. It asks for a
title, puts the note in the binder's `research` folder and lists it under
the binder's research (outside a binder, the note goes in a `research`
folder beside the document). Each of your requests is headed with the
command it came from, as in "Me: Feedback", and shows the passage it was
about; the note naming the project's files that Inkmill adds to every
request is left out. Each reply keeps its final text and the files Claude
looked at, and requests you typed in Claude Code itself are included as
you wrote them. Saving again later makes a new note; nothing is
overwritten. The note's front matter records the conversation's id.

Inkmill reads the conversation from Claude Code's own files, under
`~/.claude/projects` (`%USERPROFILE%\.claude\projects` on Windows), or
under `CLAUDE_CONFIG_DIR` when that is set. If Claude Code has deleted the
conversation, there is nothing to save; the turns are still in the
project's record (see Earlier turns).

### Letting Claude read the files

With project files on, a request names files instead of carrying their
text: it tells Claude the project folder, the binder, the story bible and the
document you are in, and Claude reads what the question needs. While it
reads, the panel shows what, as in "Reading chapter-04.md...". This keeps the
conversation small, so it lasts longer before being compacted, and lets
Continuity Check work on books too long to send in one request.

Claude reads what you see, not only what is saved. When a document has
unsaved changes, Inkmill writes a copy of the editor's text to its own state
folder and points Claude at the copy.

With project files off, each command sends its text the same way the API
providers do, and nothing else is readable.

### Termux

Anthropic does not publish an Android build of Claude Code, and the plain
`npm install -g @anthropic-ai/claude-code` no longer gives a working program
on Termux. If you already have `claude` working in Termux, Inkmill just
needs to find it: `command -v claude` shows the path to give in AI Settings
if it is not on Inkmill's PATH.

If your `claude` only runs inside a Linux distribution under `proot-distro`,
run Inkmill inside that same distribution (install it there with pip or
pipx), so both see the same files and the same folders. Starting the
distribution's `claude` from Inkmill running in plain Termux does not work,
because the program would not see your book's folder at the same path.

Each request starts the `claude` program, which takes a few seconds before
the reply begins; on a phone, expect a little longer.

### When something goes wrong

| Message | What to do |
|---------|------------|
| Cannot find the Claude Code program | Install it (above), or give its full path in AI Settings |
| Claude Code is not logged in | Run `claude` in a terminal, log in with `/login`, and try again |
| Your Claude plan's usage limit was reached | Wait for the limit to reset; Claude Code's `/usage` shows when |
| Claude Code no longer has the earlier conversation | The conversation was deleted or the book folder moved; Inkmill starts a new one by itself. The story bible still applies |

## The story bible

The story bible is a Markdown file in the project's folder, `Story
Bible.md` unless you name another in settings. Keep the facts you have
settled in it: characters' names, ages, looks and relationships, places,
the timeline, and the voice you want. AI > Story Bible opens it, creating it
from a short template the first time.

Every AI request uses it, with every provider. Claude Code reads the file
when a question touches what it covers; the other providers are sent it
with each request (Claude caches it, so this costs little after the first
question). Continuity Check also reports passages that contradict it.

In the reply panel, B appends the reply to the story bible under a dated
heading, for answers worth keeping such as a character sheet you asked for.
Edit it down afterwards; it is your file.

AI > Update Story Bible from Conversation reads the project's whole
conversation (every turn Conversation History lists) and the story bible,
and suggests entries for what the conversation settled that the bible
does not yet say: who people are, places, the timeline, the plot and the
style. Ideas you rejected or left undecided are left out. Each suggestion
names the bible heading it belongs under, and says so when it contradicts
something the bible already holds. They are listed with every one checked;
uncheck the ones that are wrong (Space or Enter), then press A or choose
Add checked. Each entry is added as a bullet at the end of its heading's
section, and a heading the bible lacks is added at the end. If the bible
is open with unsaved changes, the entries go into the open copy, to save
or undo as usual.

This request is not part of the conversation and is not listed in its
history. With Claude Code reading project files, Inkmill writes the
conversation to `.inkmill/conversation-for-bible.md` for Claude to read;
otherwise the conversation (its newest turns, up to half of
`max_context_chars`) and the bible go with the request. Run it again after
more discussion: it suggests only what the bible does not already say.

## Privacy

Nothing is sent until you run an AI command, and only the text that command
names: the selection, the document, or for Continuity Check the binder and
its research notes (it asks first). The story bible goes with each request
when there is one. The first request to each server, or to Claude Code,
asks for your permission.

API keys are read from `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in your
environment, or from a file in the `ai` folder beside settings.toml that
only your user can read. They are never written to settings.toml. Claude
Code needs no key in Inkmill at all.

Claude Code runs as a writing assistant only. It does not load your Claude
Code settings, hooks, plugins, MCP servers or CLAUDE.md files. It gets no
tools at all, or with project files on, only the read-only Read, Grep and
Glob tools. Claude Code limits those to the project folder, the folders
holding the binder's chapters and research, and Inkmill's folder of
unsaved-change copies. It cannot run commands, browse the web, or change any
file. Replies reach your text only when you press I, R or 1 to 3.

The record of each project's conversation is a plain file in the
project's `.inkmill` folder, so it goes wherever the folder goes: Git
Sync commits it, and any folder sync copies it. Delete the folder to
forget the turns, or set `keep_history = false`.

## Settings

```toml
[plugins.ai]
provider = "anthropic"     # or "claude-code", "ollama", "openai"
model = "claude-sonnet-5-5"
base_url = ""              # a different server address
max_tokens = 2048
max_tokens_long = 4096     # for Continuity Check
max_context_chars = 600000
story_bible = "Story Bible.md"
keep_history = true        # keep every turn in the project's .inkmill folder

# Claude Code only
command = "claude"         # the program, a full path, or a wrapper command
file_access = true         # let Claude read the project's files
effort = ""                # low, medium, high...; empty for Claude Code's default
```

Claude Code keeps which conversation belongs to which project in
`claude-code-sessions.json` in Inkmill's state folder; deleting it makes
every project start a new conversation.
