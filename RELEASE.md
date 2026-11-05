# Cosmos Arche · 0.2.3

Deployment and backend lifecycle improvements for Linux x86_64 / x86-64-v2, packaged separately for glibc ≥ 2.28 (AlmaLinux 8) and ≥ 2.34 (AlmaLinux 9).

- Installation announces connections before waiting, retries transient failures and supports explicit offline installation. Local compatible archives can be selected across glibc tiers.
- Core includes terminfo data and terminal fallback; SSH truecolor settings are propagated.
- Private native libraries are isolated from host ROOT/Conda library paths. Internal Bash restores the host environment and deduplicates paths.
- HOME display follows the current user, directory boundaries and symlink aliases.
- The bundled backend is `cosmos-tmux`, with independent sockets and verified process ownership. `cosmos stop --all` previews sessions/tasks before closing owned backends; plain `stop` retains terminal sessions.
- Each installation includes `uninstall.sh` with process checks and confirmation. User configuration/cache/state are retained.
- Concise English and Chinese READMEs link to detailed documentation.

Download a core binary archive, extract it and run `./install.sh`. Select optional Agent, PDF and Rime＋雾凇 components as needed. Offline preparation, compatibility, installation paths and update behavior are documented in [the installation guide](docs/installation.md).

Existing backends retain their original name and environment until stopped and restarted. Replacing installation files does not restart running sessions. Review the `cosmos stop --all` preview carefully: confirming it ends the listed terminal applications and pending work.

This is a development/prerelease build. It does not claim complete delivery of all planned features. Cosmos is MIT licensed; bundled dependencies retain their own licenses and applicable source archives.
