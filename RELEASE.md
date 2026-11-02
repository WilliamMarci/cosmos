# Cosmos Arche · 0.2.1

- Channel: development — next-version work, not a final release
- Date: 2026-11-02
- Author: William Marci
- Initial target: Linux x86_64

The first Arche development baseline remains tagged v0.1.0. This branch adds rich document reading, persistent reader caching/adaptive PDF rendering and the first movable Calendar UI package. It is not a claim that the full planned first-version scope is complete or that external Mod APIs are frozen permanently. The application version is 0.2.1; the JSON-RPC wire protocol remains major 1, minor 4, and configuration format version remains 1. These version numbers serve different purposes.

## 0.2.1 changes

Captured terminal tabs are expanded to pane-local display columns before UI rendering and Agent observation/control inference. Status labels use session names and position indices while actions retain stable pane identities; clicking the status position opens Switch. Agent approval and completion notifications integrate with the existing notification stack.

## Included

Python/Textual and Cosmos-owned UI surfaces; persistent Tmux sessions and pane operations; local IPC, settings, Mod lifecycle and events; terminal history and single-pane search; command assistant integration; image/PDF and local EPUB/Markdown/HTML reading with search, outline, page navigation, bounded memory/disk caching and adaptive raster budgets; Calendar UI Mod with date click popup and separate enable/notification policy; Rime input including the command assistant; configurable status blocks and notification stacks; session CLI, Bash completion and application mouse passthrough.

## Requirements and limits

The Linux archive includes the coordinator, Python sources, native Bash adapter source, examples, SDK, documentation, licenses and checksums. It does not include a ready Python virtual environment, system Tmux, Poppler, a complete Rime runtime/dictionary bundle or a precompiled Bash adapter. Setup is documented in README.md and python/README.md. Kitty/Ghostty image support has local verification; remote/mobile combinations and clean-machine installation are not universally validated.

Not included: integrated Yazi file management/left panel, service-wide terminal search, PDF text selection/copy compatibility layer. OCR and SVG/EPS/ICO extensions are outside the current required scope. Future work belongs in design/.

## Upgrading a running workspace

Detach Cosmos clients before replacing the coordinator. Run `cosmos stop`, then reopen `cosmos`. Tmux applications remain running; coordinator-managed Mods stop and must be restarted as appropriate. A newly opened terminal otherwise reconnects to the old persistent service. No automatic shutdown of a user's running service is performed by the release procedure.

Arche 0.1.0 release documentation and source remain available at the v0.1.0 Git tag. This next-version work does not replace that tag or its archive.
