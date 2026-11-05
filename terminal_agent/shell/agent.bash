# Source in an interactive Bash. Python paints only the popup; Readline owns PS1.
# Resolve the sourced file itself, including symlinks. Never use the caller's
# working directory or CDPATH to find project sources and build artifacts.
_TERMINAL_AGENT_SOURCE=$(readlink -f -- "${BASH_SOURCE[0]}") || return
_TERMINAL_AGENT_ROOT=$(CDPATH= builtin cd -- "$(dirname -- "$_TERMINAL_AGENT_SOURCE")/.." && builtin pwd -P) || return
unset _TERMINAL_AGENT_SOURCE
_terminal_agent_python() {
    local agent_python=${TERMINAL_AGENT_PYTHON:-}
    local -a agent_python_flags=()
    if [[ -f ${_TERMINAL_AGENT_ROOT%/*}/installed-features.json ]]; then
        agent_python="${_TERMINAL_AGENT_ROOT%/*}/.venv/bin/python"
        agent_python_flags=(-I)
        export TERMINAL_AGENT_ISOLATED=1
    else
        unset TERMINAL_AGENT_ISOLATED
    fi
    if [[ -z $agent_python ]]; then
        if [[ -x $_TERMINAL_AGENT_ROOT/.venv/bin/python ]]; then
            agent_python=$_TERMINAL_AGENT_ROOT/.venv/bin/python
        else
            agent_python=$(type -P python3) || return
        fi
    elif [[ $agent_python != /* ]]; then
        if [[ $agent_python == */* ]]; then
            # A project-relative override stays valid after cd elsewhere.
            agent_python=$_TERMINAL_AGENT_ROOT/$agent_python
        else
            agent_python=$(type -P "$agent_python") || return
        fi
    fi
    if [[ ! -x $agent_python ]]; then
        printf 'terminal-agent: Python interpreter not executable: %s (unset TERMINAL_AGENT_PYTHON to auto-detect)\n' "$agent_python" >&2
        return 1
    fi
    if ! "$agent_python" "${agent_python_flags[@]}" -c 'import prompt_toolkit' >/dev/null; then
        printf 'terminal-agent: dependency import failed with %s (actual exception above)\n' "$agent_python" >&2
        return 1
    fi
    TERMINAL_AGENT_PYTHON=$agent_python
}
_terminal_agent_python || return
_terminal_agent_load() {
    local agent_build="$_TERMINAL_AGENT_ROOT/.build"
    local agent_module="$_TERMINAL_AGENT_ROOT/.build/terminal-agent-readline.so"
    if [[ ! -f $agent_module || $_TERMINAL_AGENT_ROOT/native/readline.c -nt $agent_module ]]; then
        mkdir -p -- "$agent_build" || return
        # Publish atomically: a previously sourced Bash may still map the old SO.
        local agent_tmp="$agent_module.$$.tmp"
        if ! "${CC:-cc}" -shared -fPIC -Wall -Wextra -Werror -O2 \
            "$_TERMINAL_AGENT_ROOT/native/readline.c" -o "$agent_tmp" -ldl; then
            rm -f -- "$agent_tmp"
            return 1
        fi
        mv -- "$agent_tmp" "$agent_module" || return
    fi
    if [[ $(type -t terminal_agent_native) == builtin ]]; then
        terminal_agent_native reset
        enable -d terminal_agent_native || return
    fi
    enable -f "$agent_module" terminal_agent_native || return
    terminal_agent_native install "$_TERMINAL_AGENT_ROOT"
}
# Clear an active session from the older bind -x adapter before migrating.
if declare -F _terminal_agent_finish >/dev/null; then
    _terminal_agent_finish
fi
_terminal_agent_load || return
_terminal_agent_prompt_cleanup() {
    local agent_previous_status=$?
    terminal_agent_native reset
    return "$agent_previous_status"
}
# Old source versions registered this name in PROMPT_COMMAND. Keep that hook
# working while switching the actual implementation to native Readline.
_terminal_agent_finish() { _terminal_agent_prompt_cleanup; }
if [[ ${_TERMINAL_AGENT_NATIVE_HOOK_INSTALLED:-0} != 1 ]]; then
    if [[ $(declare -p PROMPT_COMMAND 2>/dev/null) == 'declare -a '* ]]; then
        PROMPT_COMMAND+=(_terminal_agent_prompt_cleanup)
    else
        PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND; }_terminal_agent_prompt_cleanup"
    fi
    _TERMINAL_AGENT_NATIVE_HOOK_INSTALLED=1
fi

# Advertise the native Readline adapter to the optional Cosmos presenter.
if [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]]; then
    "${COSMOS_TMUX:-tmux}" -S "${TMUX%%,*}" set-option -p -t "$TMUX_PANE" @cosmos_terminal_agent 1
fi
