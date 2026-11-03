#!/usr/bin/env bash
# Line-based TUI: works over SSH, TERM=dumb and terminals without cursor APIs.
set -euo pipefail
bundle=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    cat <<'HELP'
Usage: ./install.sh [--prefix DIR] [--bin-dir DIR]
                    [--features core,agent,assistant,pdf,rime] [--yes] [--check]
Default installation: ~/.local/share/cosmos/VERSION; command: ~/.local/bin/cosmos
No sudo, shell startup edits, system package installation or global environment changes.
Feature archives can be placed beside install.sh for offline installation.
HELP
    exit 0
fi
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'Requires Linux x86_64.' >&2; exit 1; }
for command in getconf cp mkdir ln df grep; do
    command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 1; }
done
glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null || true)
glibc=${glibc#glibc }
[[ $glibc =~ ^([0-9]+)\.([0-9]+) ]] && (( BASH_REMATCH[1] > 2 || (BASH_REMATCH[1] == 2 && BASH_REMATCH[2] >= 28) )) || {
    echo 'Requires glibc 2.28+ (AlmaLinux/Rocky/RHEL 8+, compatible distributions). musl/Alpine is not supported.' >&2; exit 1;
}
# CPython and the baseline Agent build use the x86-64-v2 instruction subset.
for flag in sse4_1 sse4_2 ssse3 popcnt cx16 lahf_lm; do
    grep -qw "$flag" /proc/cpuinfo || { echo "No compatible package: CPU lacks $flag (x86-64-v2 required)." >&2; exit 1; }
done
[[ -x $bundle/runtime/bin/python3 ]] || { echo 'Portable Python runtime missing; use the binary release archive, not GitHub source.zip.' >&2; exit 1; }
features=core,agent,assistant
location_args=()
explicit=0
for arg in "$@"; do [[ $arg == --features || $arg == --features=* || $arg == --yes || $arg == --check ]] && explicit=1; done
if (( ! explicit )); then
    [[ -t 0 && -t 1 ]] || { echo 'Non-interactive install requires --yes or --features.' >&2; exit 2; }
    version=$("$bundle/runtime/bin/python3" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$bundle/bundle.json")
    prefix=${XDG_DATA_HOME:-$HOME/.local/share}/cosmos/$version
    bin_dir=$HOME/.local/bin
    arguments=("$@")
    for ((i=0; i<${#arguments[@]}; i++)); do
        case "${arguments[i]}" in
            --prefix) i=$((i+1)); prefix=${arguments[i]:-} ;;
            --prefix=*) prefix=${arguments[i]#*=} ;;
            --bin-dir) i=$((i+1)); bin_dir=${arguments[i]:-} ;;
            --bin-dir=*) bin_dir=${arguments[i]#*=} ;;
        esac
    done
    selected=(1 1 0 0)
    labels=('Cosmos Agent (separate archive)' 'Bash command assistant' 'PDF reader (private Poppler)' 'Rime input method (private librime + rime_ice)')
    while true; do
        printf '\nCosmos installation — Core is required\n'
        for i in 0 1 2 3; do
            mark=' '; [[ ${selected[i]} == 1 ]] && mark=x
            printf '  %d [%s] %s\n' "$((i+1))" "$mark" "${labels[i]}"
        done
        printf '  p Installation directory: %s\n  b Command directory: %s\n' "$prefix" "$bin_dir"
        printf 'Toggle 1–4; p/b edits directories; Enter continues; q cancels: '
        read -r answer || exit 1
        [[ $answer == q ]] && exit 0
        [[ -z $answer ]] && break
        if [[ $answer == p || $answer == b ]]; then
            printf 'New directory (empty keeps current): '
            read -r directory || exit 1
            if [[ -n $directory ]]; then
                if [[ $answer == p ]]; then prefix=$directory; else bin_dir=$directory; fi
            fi
            continue
        fi
        for number in $answer; do
            case "$number" in 1|2|3|4) i=$((number-1)); selected[i]=$((1-selected[i])) ;; *) echo "Invalid choice: $number" ;; esac
        done
    done
    location_args=(--prefix "$prefix" --bin-dir "$bin_dir")
    names=(agent assistant pdf rime)
    features=core
    for i in 0 1 2 3; do [[ ${selected[i]} == 1 ]] && features+=,${names[i]}; done
fi
# -I ignores the caller's Python environment; all installation code is bundled.
exec "$bundle/runtime/bin/python3" -I "$bundle/installer.py" --bundle "$bundle" --default-features "$features" "$@" "${location_args[@]}"
