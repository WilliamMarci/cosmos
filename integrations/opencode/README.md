# Cosmos Agent / OpenCode integration

Upstream: https://github.com/anomalyco/opencode
Pinned base: `c93aaae37157d785f76a8e9a9243a6560e286468` (2.1.2).
License: MIT, preserved in `LICENSE-OpenCode`.

`isolation.patch` disables upstream global configuration discovery for Cosmos launches; the launcher provides only Cosmos-owned configuration and explicit skill roots. Stock OpenCode compatibility additionally uses its discovery-home override without changing shell HOME.

`branding.patch` is the small opt-in modification of upstream Logo and session epilogue. `cosmos-logo.tsx` is Cosmos-owned presentation using OpenCode semantic text roles. The generated glyph data comes from Cosmos's canonical `python/cosmos_tui/assets/cosmos-logo.ansi`; no independent logo copy is maintained. Ordinary OpenCode rendering is unchanged unless `COSMOS_AGENT=1`.

`dev/prepare_agent.py` applies the patch idempotently without resetting the checkout. It fails if the patch neither applies nor matches an already-applied patch. The ignored vendor checkout is a development runtime, not the only copy of the integration. `dev/setup_agent.sh` installs the local Bun runtime/dependencies, fixes upstream PTY permissions and applies the tracked patch. This does not build a release package. The separate `packaging/build_agent.sh` compiles the patched CLI for the release recipe; `packaging/build.sh --without-agent` omits it and the runtime can use system OpenCode instead.

`agent.test.ts` is a focused OpenCode-side schema and permission-rule test. Copy it to `vendor/opencode/packages/core/test/cosmos-agent.test.ts` and run there with `COSMOS_AGENT_TEST_CONFIG=/absolute/path/config.json bun test test/cosmos-agent.test.ts`. Generate that JSON with `cosmos_tui.features.agent.launch.configuration(socket, source_pane)`.

The terminal tools and launcher live in `python/cosmos_tui/features/agent/`, outside the upstream tree. See `docs/agent.md` for the implemented API and limits.
