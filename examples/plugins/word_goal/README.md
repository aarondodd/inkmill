# Word Goal

Set how many words you want to write in this session, then check how far
along you are.

| Command | Key | What it does |
|---------|-----|--------------|
| Tools > Set Word Goal... | | Asks for a target, 500 by default |
| Tools > Goal Progress | Ctrl+F8 | Shows a progress bar in the status line |

Progress counts from the moment you set the goal (or first ask for
progress) in each document, so opening a long draft does not count its
existing words.

Settings, in settings.toml:

```toml
[plugins.word_goal]
goal = 1000
```

This plugin is also the smallest complete example of the plugin API; read
its `__init__.py` alongside `docs/plugins.md`.
