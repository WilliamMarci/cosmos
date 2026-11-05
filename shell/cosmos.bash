# Restore the host environment before user startup code. Cosmos itself starts
# with a clean loader environment; its private ELF dependencies use RPATH.
if [[ ${COSMOS_HOST_ENV_ACTIVE:-0} == 1 ]]; then
    for _cosmos_name in PATH LD_LIBRARY_PATH LD_PRELOAD PYTHONPATH PYTHONHOME; do
        _cosmos_key=COSMOS_HOST_$_cosmos_name
        _cosmos_set=${_cosmos_key}_SET
        if [[ ${!_cosmos_set:-0} == 1 ]]; then
            printf -v "$_cosmos_name" '%s' "${!_cosmos_key}"
            export "$_cosmos_name"
        else
            unset "$_cosmos_name"
        fi
        unset "$_cosmos_key" "$_cosmos_set"
    done
    unset COSMOS_HOST_ENV_ACTIVE _cosmos_name _cosmos_key _cosmos_set
fi
# Bash rcfile for new Cosmos panes; ordinary user configuration stays first.
[[ -f ~/.bashrc ]] && source ~/.bashrc
_cosmos_entry_root=$(CDPATH= builtin cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && builtin pwd -P)
source "${COSMOS_RC:-$_cosmos_entry_root/config/cosmosrc}"
# Startup files commonly append ROOT/Conda paths again in a nested shell.
# Keep the first occurrence and preserve meaningful empty path entries.
_cosmos_deduplicate_path() {
    local name=$1 remaining=${!1} part joined='' first=1
    local -A seen=()
    while true; do
        part=${remaining%%:*}
        if [[ ${seen["_$part"]+present} != present ]]; then
            seen["_$part"]=1
            if (( first )); then joined=$part; first=0; else joined+=:$part; fi
        fi
        [[ $remaining == *:* ]] || break
        remaining=${remaining#*:}
    done
    printf -v "$name" '%s' "$joined"
}
for _cosmos_name in PATH LD_LIBRARY_PATH PYTHONPATH; do
    [[ -v $_cosmos_name ]] && _cosmos_deduplicate_path "$_cosmos_name"
done
unset -f _cosmos_deduplicate_path
unset _cosmos_entry_root _cosmos_name
