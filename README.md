# Cosmos

[English](README.md) · [简体中文](README.zh-CN.md)

Cosmos is a terminal workspace for local machines and SSH servers. Reconnect to persistent sessions, work across panes, read documents, and use an AI agent without installing a companion client on your laptop.

## Features

- Persistent sessions, windows and split panes, with scrollback and search.
- An integrated Reader for images, PDF, EPUB, Markdown and HTML; `cosmos open FILE` also opens Reader on its own.
- An optional AI Agent with terminal observation and interaction tools, plus a Bash command assistant.
- Optional Rime input with the 雾凇 configuration, themes, notifications and extensions.

Cosmos is under active development. See the [release notes](RELEASE.md) for the current scope.

## Install

Download a **core binary archive** from [Releases](https://github.com/WilliamMarci/cosmos/releases), extract it, and run:

```bash
./install.sh
```

The installer lets you choose the installation directory and optional Agent, PDF and Rime components. It installs as your user; Python and native runtime dependencies are bundled, so no compiler or system package installation is needed.

Packages currently target **Linux x86_64 / x86-64-v2**, with **glibc ≥ 2.28** or **≥ 2.34** compatibility tiers. Use the core binary archive rather than GitHub’s generated source archive. For offline installation, custom paths and compatibility details, see the [installation guide](docs/installation.md).

```bash
cosmos                    # open or reconnect to the main workspace
cosmos attach work        # open a named session
cosmos open document.pdf  # open Reader directly outside Cosmos
cosmos update             # update a release installation
```

## Documentation

- [Commands and sessions](docs/cli.md) · [Settings](docs/settings.md) · [Shell integration](docs/shell.md)
- [Reader](docs/viewer.md) · [Agent](docs/agent.md) · [Input method](docs/input-method.md)
- [Themes](docs/themes.md) · [Notifications](docs/notifications.md) · [Extensions](docs/ui-mods.md)
- [Development](docs/development.md) · [Architecture](docs/architecture.md) · [RPC](docs/framework.md)

## Upstream projects

Cosmos builds on [Tmux](https://github.com/tmux/tmux), [Textual](https://github.com/Textualize/textual), [OpenCode](https://github.com/anomalyco/opencode), [librime](https://github.com/rime/librime), [雾凇](https://github.com/iDvel/rime-ice) and [Poppler](https://poppler.freedesktop.org/). Additional design references and pinned source revisions are listed in the [upstream registry](vendor/README.md) and [source manifest](vendor/sources.json).

Cosmos is [MIT licensed](LICENSE). Bundled third-party components retain their own licenses; notices and applicable source archives accompany release packages.
