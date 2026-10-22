# Bash startup for Cosmos panes. User configuration is loaded first.
[[ -f ~/.bashrc ]] && source ~/.bashrc
_cosmos_root=$(CDPATH= builtin cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && builtin pwd -P)
export TERMINAL_AGENT_PYTHON="${COSMOS_PYTHON:-$_cosmos_root/.venv/bin/python}"
source "$_cosmos_root/terminal_agent/shell/agent.bash"
unset _cosmos_root
