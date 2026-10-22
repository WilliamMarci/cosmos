# Bash completion for the public Cosmos entry point. No daemon is started.
_cosmos_complete() {
    local cur=${COMP_WORDS[COMP_CWORD]} command=${COMP_WORDS[1]} previous=${COMP_WORDS[COMP_CWORD-1]}
    local commands='attach daemon stop doctor config events mod action rpc open cache-clear completion help'
    COMPREPLY=()
    if (( COMP_CWORD == 1 )); then
        mapfile -t COMPREPLY < <(compgen -W "$commands --help --version --debug --log-level --log-file" -- "$cur")
        return
    fi
    case "$previous" in
        --log-level) mapfile -t COMPREPLY < <(compgen -W 'DEBUG INFO WARNING ERROR' -- "$cur"); return ;;
        --log-file|open|add) mapfile -t COMPREPLY < <(compgen -f -- "$cur"); compopt -o filenames; return ;;
    esac
    case "$command" in
        help) mapfile -t COMPREPLY < <(compgen -W "$commands" -- "$cur") ;;
        completion) mapfile -t COMPREPLY < <(compgen -W 'bash' -- "$cur") ;;
        mod)
            if (( COMP_CWORD == 2 )); then
                mapfile -t COMPREPLY < <(compgen -W 'list add start stop remove --help' -- "$cur")
            fi ;;
        rpc)
            if (( COMP_CWORD == 2 )); then
                mapfile -t COMPREPLY < <(compgen -W 'health initialize state.snapshot actions.list actions.invoke mods.list mods.register mods.start mods.stop mods.unregister events.poll settings.get settings.replace notifications.list' -- "$cur")
            fi ;;
        attach|--debug|--log-level|--log-file)
            mapfile -t COMPREPLY < <(compgen -W '--debug --log-level --log-file --help' -- "$cur") ;;
        *) mapfile -t COMPREPLY < <(compgen -W '--help' -- "$cur") ;;
    esac
}
complete -F _cosmos_complete cosmos
