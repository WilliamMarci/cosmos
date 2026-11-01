---
name: cosmos-skill-export
description: Turn an observed software-operation workflow into a reusable Cosmos/OpenCode skill, or update and export an existing skill. Use when the user asks to remember, save, share or reuse how to operate a terminal application.
---

# Export a learned software workflow

Extract the reusable workflow from this conversation and tool results. Save a standard skill directory with `SKILL.md` YAML frontmatter (`name`, `description`, and `metadata.cosmos/software` triggers naming the application/executables), plus supporting files only when they remove real duplication. Use [the template](references/skill-template.md) to cover the relevant evidence; do not copy empty sections mechanically.

## Select the scope

Choose a short lowercase hyphenated name under 64 characters, such as `vim-edit-config` or `gdb-inspect-stack`. Describe the software and task in discovery metadata. Prefer one useful task or closely related task family over an entire application's manual. The workflow must not depend on this conversation being available.

Default destination is the personal Cosmos skill library identified in the Agent system context. Use the project's `.cosmos/skills/` if requested, or another destination the user specifies. Read an existing same-name skill before updating it; preserve still-valid content rather than replacing it with a transcript of this one run. The requested skill export authorizes creating these skill files, not unrelated changes or external publication.

## Supplement an existing skill

For additional learning, read the existing entrypoint and only the supporting files relevant to the requested addition. Keep its name and destination, and merge new verified operations or corrections into the relevant sections. Preserve unrelated validated content, triggers and supporting files; do not create a duplicate skill or append a transcript. Exercise only the new or changed steps, plus any directly affected checkpoint. If evidence contradicts an existing step, record the applicable version/environment and correct it; label unresolved differences as unverified. If no reusable new evidence was obtained, leave the existing skill unchanged. Report the additions, corrections and verification gaps after validation and readback.

## Distill the evidence

- Record non-obvious controls, modes, prerequisites and the cues used to distinguish them. Rediscover session/window/pane IDs at runtime. Express cursor positions relative to UI elements instead of fixed coordinates.
- Give each important operation an observable checkpoint. Include a concrete recovery path for failures actually encountered, and a bounded stop condition if the application doesn't match expectations.
- Separate steps actually exercised from documentation-derived or proposed steps. Report software version/environment when known, and say what remains unverified. Never invent a successful test.
- Parameterize file names, paths and queries. Remove task data, credentials, personal content, conversation dumps and ephemeral IDs. Use neutral example values. A failure worth preserving should explain its trigger and recovery, not become an unrelated universal prohibition.
- Save scripts only when a repeated deterministic operation merits one. Test any new script in an isolated fixture before calling it verified. Keep large application-specific detail in relative `references/` files and link it from `SKILL.md`.

## Verify and deliver

Read the finished skill back. Check that a fresh Agent can discover when to use it, identify its target, perform the steps and assess success without this conversation. Confirm every referenced file exists and the description matches the actual procedure. A replay that changes user state still follows the user's task scope and OpenCode permissions; exporting alone does not authorize that replay.

Report the saved directory, verified scope and any gaps. If the user requests a portable archive, package the directory with:

```sh
python -m cosmos_tui.features.agent.skills pack /path/to/skill --output /path/to/skill.zip
```

The resulting ZIP contains a single skill root. On another installation, extract that directory into its Cosmos personal or project skill library. Skill discovery updates through OpenCode's file watcher; if watchers are disabled, reopen the Agent. Packaging validates the entrypoint and references but does not certify that the described workflow succeeds.
