# Command assistant file access

Settings → Command assistant → File access offers No access, Read only (default), and Read & write. The setting is persisted with the other Cosmos configuration as `assistant_file_access = "none" | "read_only" | "read_write"`. A coordinator built with this field is required to save it; an older coordinator rejects the unknown setting through the normal notification path.

Each new generation uses the current Cosmos setting, including an already open assistant. Standalone terminal-agent uses `file_access` in its own configuration with the same values and default.

No access disables file tools. Read only enables read, glob, grep and directory listing. Read & write additionally enables file creation and editing, scoped to the supplied target directory and descendants; the prompt permits modifications only when explicitly requested. All modes deny automatic Shell execution, subagents and other tools. The proposed command is still inserted into Bash for the user to review and execute.

The backend continues to run in its separate application workspace and receives the target directory explicitly. Prompts require absolute paths for tool calls. OpenCode V1 and V2 permission formats are supplied; these are tool policies rather than an operating-system sandbox. This setting does not change the permissions of a separately launched full OpenCode session.
