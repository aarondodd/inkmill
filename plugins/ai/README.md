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
| New Conversation | Claude Code only: start a fresh conversation for this project |
| Continue in Claude Code... | Claude Code only: the command that opens this project's conversation in Claude Code itself |
| Save Conversation as Research Note... | Claude Code only: writes this project's conversation into a note in the binder's research (see below) |
| Set API Key... | Store your key (API providers) |
| AI Settings... | Choose the provider, model and server or program |

In the reply panel: I inserts the reply at the cursor, R replaces the text
you selected, 1 to 3 pick a rewrite, Q asks a follow-up question in the same
conversation, B adds the reply to the story bible, C copies the reply, and
Esc closes the panel (and stops a reply still arriving).

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

Use AI > New Conversation when you start on something unrelated, or when
replies start missing earlier details. Very long conversations are
summarized by Claude Code to make room ("compacted"), and a summary keeps
less detail than the original. That is what the story bible is for.

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
conversation, there is nothing to save.

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

# Claude Code only
command = "claude"         # the program, a full path, or a wrapper command
file_access = true         # let Claude read the project's files
effort = ""                # low, medium, high...; empty for Claude Code's default
```

Claude Code keeps which conversation belongs to which project in
`claude-code-sessions.json` in Inkmill's state folder; deleting it makes
every project start a new conversation.
