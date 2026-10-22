# Bash rcfile for new Cosmos panes; ordinary user configuration stays first.
[[ -f ~/.bashrc ]] && source ~/.bashrc
_cosmos_entry_root=$(CDPATH= builtin cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && builtin pwd -P)
source "${COSMOS_RC:-$_cosmos_entry_root/config/cosmosrc}"
unset _cosmos_entry_root
