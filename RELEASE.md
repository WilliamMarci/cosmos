# Cosmos Arche · 0.1.0

- Channel: development — first development release
- Date: 2026-10-23
- Author: William Marci
- Initial target: Linux x86_64

Arche names the first development baseline. It is not a claim that the full planned first-version scope is complete or that external Mod APIs are frozen permanently. The application version is 0.1.0; the JSON-RPC wire protocol remains major 1, minor 4, and configuration format version remains 1. These version numbers serve different purposes.

## Included

Python/Textual and Cosmos-owned UI surfaces; persistent Tmux sessions and pane operations; local IPC, settings, Mod lifecycle and events; terminal history and single-pane search; command assistant integration; image/PDF reading with search, outline, page navigation and bounded memory caching; Rime input including the command assistant; configurable status blocks and notification stacks; session CLI, Bash completion and application mouse passthrough.

## Requirements and limits

The Linux archive includes the coordinator, Python sources, native Bash adapter source, examples, SDK, documentation, licenses and checksums. It does not include a ready Python virtual environment, system Tmux, Poppler, a complete Rime runtime/dictionary bundle or a precompiled Bash adapter. Setup is documented in README.md and python/README.md. Kitty/Ghostty image support has local verification; remote/mobile combinations and clean-machine installation are not universally validated.

Not included: integrated Yazi file management/left panel, service-wide terminal search, global Agent tools/permissions bridge, persistent reader disk cache, EPUB/Markdown readers, PDF text selection/copy compatibility layer. OCR and SVG/EPS/ICO extensions are outside the current required scope. Future work belongs in design/.

## Upgrading a running workspace

Detach Cosmos clients before replacing the coordinator. Run `cosmos stop`, then reopen `cosmos`. Tmux applications remain running; coordinator-managed Mods stop and must be restarted as appropriate. A newly opened terminal otherwise reconnects to the old persistent service. No automatic shutdown of a user's running service is performed by the release procedure.
