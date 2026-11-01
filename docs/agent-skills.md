# Cosmos Agent skills

Cosmos uses OpenCode's native skill registry and `skill` tool. A skill is a portable directory containing `SKILL.md` with YAML `name` and `description` frontmatter. Its body describes a task workflow; optional relative `references/`, `scripts/` and `assets/` hold details and reusable helpers. There is no second model-side registry or transcript database.

## Discovery

Every Cosmos Agent launch adds these discovery roots:

- Bundled: `<Cosmos installation>/skills/`.
- Personal: `${XDG_CONFIG_HOME:-~/.config}/cosmos/agent/skills/`.
- Project: `<Agent working directory>/.cosmos/skills/`.

Ordinary OpenCode, Claude and `.agents` skill sources are not imported. Inherited `OPENCODE_CONFIG_CONTENT` is discarded rather than merged. Explicit additional sources must be configured in Cosmos's own `~/.config/cosmos/agent/opencode.json`. The private profile is initialized at Agent launch; skill directories are created when skills are saved. Existing same-name skills should be inspected before updating; use distinct task names when multiple sources provide different procedures.

Skills are listed by metadata and loaded on demand through the existing tool. OpenCode watches the configured directories and refreshes the registry after files change; when file watching is disabled, reopen the Agent to rescan. Skills are injected only into the bundled/source Cosmos Agent. Plain system OpenCode uses its own configuration and skill discovery without Cosmos injection.

Cosmos also performs deterministic application matching. A skill can declare `metadata: cosmos/software: [madgraph, mg5_aMC, vim, nvim]`; Cosmos matches those triggers and the skill-name tokens against the selected pane's program, cwd and recent visible output. When exactly one skill matches, `cosmos_context.target.skill` contains its body, so the Agent can follow it immediately without another discovery call. Multiple matches return `target.recommended_skills`, and the Agent loads the best match with the existing `skill` tool. This is selection guidance, not authorization or proof that the screen matches a previous run.

Two skills ship initially:

- `cosmos-tui`: observe/act/verify with terminal tools, distinguish command keys from text paste, discover current targets and modes, and reuse application workflows.
- `cosmos-skill-export`: distill an observed operation into a self-contained skill, preserving evidence and recovery while removing transient IDs and private task data.

## Learning and saving

Inside Cosmos Agent, type a slash command:

```text
/agent-learn Use Vim to search and replace text in a temporary file
/cosmos-learn Extend vim-search-replace with verified multi-file replacement
/cosmos-export-skill Save the verified workflow as vim-search-replace
/cosmos-export-skill Export vim-search-replace to the current project's skill library and create a ZIP
```

`agent-learn` explicitly requests discovery, scoped experimentation, result verification and saving a reusable `SKILL.md` in the isolated Cosmos Agent personal library, including `metadata.cosmos/software` triggers for later automatic matching. It validates and reads back the saved skill, parameterizes transient targets and removes secrets. Failed or unverified procedures must not be described as tested. This does not override manual pauses or tool permissions. `cosmos-learn` is an equivalent learning-and-saving alias. For supplementary learning, both commands read the existing skill and relevant references, retain its name and destination, and merge only verified additions or corrections while preserving unrelated validated content. They do not repeat the whole workflow or create duplicate skills. Conflicting evidence is qualified by version/environment; unresolved differences remain unverified. Without reusable new evidence, the existing skill stays unchanged. The response reports additions, corrections and verification gaps. `cosmos-export-skill` loads the export guidance and asks the model to create or update a skill, defaulting to the personal library. The command includes the current conversation as context; if no operation has actually been observed, the prompt requires identifying missing evidence rather than inventing a tested procedure.

The model uses OpenCode's existing file tools to write skills. There is no automatic extraction daemon, and a stored skill is not a replay macro. It must rediscover live pane IDs and adapt to the current screen. Skills do not bypass tool permissions. Exporting a skill alone does not execute its scripts or authorize another run of the recorded workflow.

The prompt files are maintained in `config/agent-commands/`; the shared Agent system prompt is `config/cosmos-agent-prompt.md`. The task template is `skills/cosmos-skill-export/references/skill-template.md`. These files are included in both Agent-enabled and Agent-omitted Cosmos packages.

## Portable export

The export helper is independent of the model. From a Cosmos environment, using the installation's Python interpreter:

```sh
python -m cosmos_tui.features.agent.skills validate ~/.config/cosmos/agent/skills/vim-search-replace
python -m cosmos_tui.features.agent.skills pack ~/.config/cosmos/agent/skills/vim-search-replace --output ./vim-search-replace.zip
```

The Agent system context supplies its exact Python interpreter and personal-library path. The helper validates YAML frontmatter, a lowercase hyphenated name under 64 characters, a nonempty description/body and local Markdown references. It writes one skill-root directory in the ZIP, using the frontmatter name. It includes ordinary supporting files but skips dotfiles, cache directories and node_modules, rejects symlinks and broken/outside references, and limits the bundle to 32 MiB. Existing output archives are not overwritten, and output must be outside the skill directory. File modes for scripts are retained in ZIP metadata.

To import, inspect and extract that single directory into the destination personal or project library. The helper does not download or install skills, execute their scripts, publish archives, certify workflow correctness or remove secrets from arbitrary file contents. The export prompt instructs the model to remove private task data before packaging.

## Validation

`dev/test_agent_skills.py` verifies directory resolution, command registration, archive export/import and rejection of missing references. `dev/validate_agent_skills.py` starts a private OpenCode server with temporary XDG/project fixtures and verifies its actual `/api/skill` and `/api/command` registries discover bundled, personal and project skills plus the registered slash commands. The fixtures also contain foreign home/project skills, OpenCode commands and an MCP that would write a sentinel if started; the test checks they are excluded and the sentinel is absent. The developer probe also retains an explicit `--system` schema/isolation diagnostic; that diagnostic is not the production fallback, which launches system OpenCode directly without injection. These checks do not call a model or claim that a model-generated skill has been behaviorally replayed.
