# Cosmos Arche · 0.2.4

Fixes release installation of Python dependencies and Agent startup behind a host proxy.

- Offline Python wheels are moved into the final private venv site-packages. The staging dependency directory is removed; runtime imports no longer rely on `PYTHONPATH`.
- The Bash assistant and Agent/MCP subprocesses use the installed interpreter in isolated mode. Host Conda and Python settings remain available to the host shell.
- Agent private loopback traffic bypasses HTTP proxies; external provider traffic retains the configured proxy.
- Failed Agent panes retain their error output and exit status. Assistant import failures report the actual exception.
- Release checks include isolated imports, a real Bash assistant pane and terminal/actions MCP handshakes.

Core is rebuilt for glibc ≥ 2.28 and ≥ 2.34. Agent, PDF and Rime native payloads are unchanged and reused from 0.2.3; compatible existing installations can reuse them during update. See [installation](docs/installation.md) for online/offline setup and custom paths. This remains a development/prerelease build.
