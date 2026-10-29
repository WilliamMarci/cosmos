# Bash completion for the public Cosmos entry point. No daemon is started.
_cosmos_complete() {
    local cur=${COMP_WORDS[COMP_CWORD]} command=${COMP_WORDS[1]} previous=${COMP_WORDS[COMP_CWORD-1]}
    local commands='agent ag attach a new n list l ls sessions kill k exists ex has rename re history hi session daemon da stop st doctor do config con events ev cache-clear ca mod m action ac rpc rp open o completion com help he'
    COMPREPLY=()
    if (( COMP_CWORD == 1 )); then
        mapfile -t COMPREPLY < <(compgen -W "$commands --help --version --debug --log-level --log-file --mouse-mode" -- "$cur")
        return
    fi
    local position=$COMP_CWORD
    if [[ $command == session ]]; then
        if (( position == 2 )); then
            mapfile -t COMPREPLY < <(compgen -W 'attach a new n list l ls kill k exists ex has rename re history hi --help' -- "$cur")
            return
        fi
        command=${COMP_WORDS[2]}
        position=$((COMP_CWORD-1))
    fi
    case "$previous" in
        --mouse-mode) mapfile -t COMPREPLY < <(compgen -W "auto cell pixel" -- "$cur"); return ;;
        --log-level) mapfile -t COMPREPLY < <(compgen -W 'DEBUG INFO WARNING ERROR' -- "$cur"); return ;;
        --log-file|--cwd|-c|--output|-o|open|add) mapfile -t COMPREPLY < <(compgen -f -- "$cur"); compopt -o filenames; return ;;
        -s|--session) return ;;
    esac
    case "$command" in
        a|attach|attach-session) command=attach ;;
        n|new|new-session) command=new ;;
        l|ls|sessions|list-sessions) command=list ;;
        k|kill-session) command=kill ;;
        ex|has|has-session) command=exists ;;
        re|rename-session) command=rename ;;
        hi) command=history ;;
        ag) command=agent ;;
        da) command=daemon ;;
        st) command=stop ;;
        do) command=doctor ;;
        con) command=config ;;
        ev) command=events ;;
        ca) command=cache-clear ;;
        m) command=mod ;;
        ac) command=action ;;
        rp) command=rpc ;;
        o) command=open ;;
        com) command=completion ;;
        he) command=help ;;
    esac
    case "$command" in
        agent)
            if (( position == 2 )); then
                mapfile -t COMPREPLY < <(compgen -W 'configure export migrate --help' -- "$cur")
            elif [[ ${COMP_WORDS[2]} == configure ]]; then
                mapfile -t COMPREPLY < <(compgen -W '--provider --model --base-url --set-key --help' -- "$cur")
            else
                mapfile -t COMPREPLY < <(compgen -W '--output --help' -- "$cur")
            fi ;;
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
        attach) mapfile -t COMPREPLY < <(compgen -W '-s --session --debug --log-level --log-file --mouse-mode --help' -- "$cur") ;;
        new) mapfile -t COMPREPLY < <(compgen -W '-s --session -d --detached -c --cwd --debug --log-level --log-file --mouse-mode --help' -- "$cur") ;;
        list) mapfile -t COMPREPLY < <(compgen -W '-j --json --help' -- "$cur") ;;
        kill|exists) mapfile -t COMPREPLY < <(compgen -W '-s --session --help' -- "$cur") ;;
        rename) mapfile -t COMPREPLY < <(compgen -W '-s --session --help' -- "$cur") ;;
        history) mapfile -t COMPREPLY < <(compgen -W '-s --session -p --pane -l --lines -a --ansi -j --json -o --output --help' -- "$cur") ;;
        *) mapfile -t COMPREPLY < <(compgen -W '--help' -- "$cur") ;;
    esac
}
complete -F _cosmos_complete cosmos
