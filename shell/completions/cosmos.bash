# Bash completion for the public Cosmos entry point. No daemon is started.
_cosmos_complete() {
    local cur=${COMP_WORDS[COMP_CWORD]} command=${COMP_WORDS[1]} previous=${COMP_WORDS[COMP_CWORD-1]}
    local commands='session new sessions history attach daemon stop doctor config events mod action rpc open cache-clear completion help'
    COMPREPLY=()
    if (( COMP_CWORD == 1 )); then
        mapfile -t COMPREPLY < <(compgen -W "$commands --help --version --debug --log-level --log-file" -- "$cur")
        return
    fi
    local position=$COMP_CWORD
    if [[ $command == session ]]; then
        if (( position == 2 )); then
            mapfile -t COMPREPLY < <(compgen -W 'new attach list history --help' -- "$cur")
            return
        fi
        command=${COMP_WORDS[2]}
        position=$((COMP_CWORD-1))
    fi
    case "$previous" in
        --log-level) mapfile -t COMPREPLY < <(compgen -W 'DEBUG INFO WARNING ERROR' -- "$cur"); return ;;
        --log-file|--output|-o|--cwd|open|add) mapfile -t COMPREPLY < <(compgen -f -- "$cur"); compopt -o filenames; return ;;
    esac
    case "$command" in
        help) mapfile -t COMPREPLY < <(compgen -W "$commands" -- "$cur") ;;
        completion) mapfile -t COMPREPLY < <(compgen -W 'bash' -- "$cur") ;;
        mod)
            if (( position == 2 )); then
                mapfile -t COMPREPLY < <(compgen -W 'list add start stop remove --help' -- "$cur")
            fi ;;
        rpc)
            if (( position == 2 )); then
                mapfile -t COMPREPLY < <(compgen -W 'health initialize state.snapshot actions.list actions.invoke mods.list mods.register mods.start mods.stop mods.unregister events.poll settings.get settings.replace notifications.list' -- "$cur")
            fi ;;
        new) mapfile -t COMPREPLY < <(compgen -W '--detached -d --cwd --help' -- "$cur") ;;
        history) mapfile -t COMPREPLY < <(compgen -W '--pane --lines --ansi --json --output -o --help' -- "$cur") ;;
        sessions|list) mapfile -t COMPREPLY < <(compgen -W '--json --help' -- "$cur") ;;
        attach|--debug|--log-level|--log-file)
            mapfile -t COMPREPLY < <(compgen -W '--debug --log-level --log-file --help' -- "$cur") ;;
        *) mapfile -t COMPREPLY < <(compgen -W '--help' -- "$cur") ;;
    esac
}
complete -F _cosmos_complete cosmos
