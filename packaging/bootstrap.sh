#!/usr/bin/env bash
# Optional single-file entry: select -> download -> checksum -> extract -> TUI.
set -euo pipefail
version=0.2.3
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Cosmos installer bootstrap: requires Linux, Bash, curl/wget, tar, sha256sum, getconf.'
    echo 'Downloads the highest compatible core from the release manifest, then opens the multi-select installer.'
    echo 'Offline: ./install.sh --offline --package-dir DIR (components.tsv, components.json and selected archives).'
    echo 'Arguments are forwarded: --prefix DIR --bin-dir DIR --features LIST --yes --check'
    exit 0
fi
[[ $(uname -s) == Linux ]] || { echo 'No compatible package: Linux is required.' >&2; exit 1; }
for tool in tar sha256sum getconf grep mktemp; do
    command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done
offline=0; package_dir=''
arguments=("$@")
for ((i=0; i<${#arguments[@]}; i++)); do
    case "${arguments[i]}" in
        --offline) offline=1 ;;
        --package-dir) i=$((i+1)); package_dir=${arguments[i]:-} ;;
        --package-dir=*) package_dir=${arguments[i]#*=} ;;
    esac
done
if (( offline )) && [[ -z $package_dir ]]; then package_dir=$(dirname -- "${BASH_SOURCE[0]}"); fi
if [[ -n $package_dir ]]; then package_dir=$(cd -- "$package_dir" && pwd -P); fi
arch=$(uname -m)
glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null || true)
[[ $glibc == glibc\ * ]] || { echo 'No compatible package: glibc is required (musl is not supported).' >&2; exit 1; }
glibc=${glibc#glibc }
major=${glibc%%.*}; minor=${glibc#*.}; minor=${minor%%.*}
cache=${XDG_CACHE_HOME:-$HOME/.cache}/cosmos
mkdir -p -- "$cache"
work=$(mktemp -d "$cache/install.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
fetch() {
    local filename=${1##*/}
    if [[ -n $package_dir && -f $package_dir/$filename ]]; then
        printf 'Use local package: %s\n' "$package_dir/$filename"
        cp -- "$package_dir/$filename" "$2"
        return
    fi
    if (( offline )); then
        echo "Offline file missing: $filename in $package_dir. Copy components.tsv, components.json and compatible selected archives from the same release. Or extract a core archive and run its install.sh --offline --package-dir DIR." >&2
        return 1
    fi
    printf 'Connect/download: %s (10s connection timeout; up to 3 attempts)\n' "$1"
    if command -v curl >/dev/null; then
        curl --fail --location --proto '=https' --tlsv1.2 --connect-timeout 10 --retry 2 --retry-connrefused --retry-delay 1 --max-time 300 --output "$2" "$1" || {
            echo 'Download failed. On an online machine, download components.tsv, components.json and compatible core/selected archives; transfer them here and run install.sh --offline --package-dir DIR.' >&2; return 1;
        }
    elif command -v wget >/dev/null; then
        wget --https-only --connect-timeout=10 --read-timeout=30 --tries=3 -O "$2" "$1"
    else
        echo 'curl or wget is required online; use --offline --package-dir DIR with local packages instead.' >&2; return 1
    fi
}
base=https://github.com/WilliamMarci/cosmos/releases/download/v$version
fetch "$base/components.tsv" "$work/components.tsv"
best_major=-1; best_minor=-1; selected=''
local_major=-1; local_minor=-1; local_selected=''
while IFS=$'\t' read -r name v a floor flags filename url sha size unpacked; do
    [[ $name == core && $v == "$version" && $a == "$arch" ]] || continue
    [[ $floor =~ ^[0-9]+\.[0-9]+$ && $sha =~ ^[0-9a-f]{64}$ ]] || continue
    fm=${floor%%.*}; fn=${floor#*.}
    (( fm < major || (fm == major && fn <= minor) )) || continue
    compatible=1
    IFS=, read -ra required <<< "$flags"
    for flag in "${required[@]}"; do grep -qw -- "$flag" /proc/cpuinfo || compatible=0; done
    (( compatible )) || continue
    if [[ -n $package_dir && $filename != */* && -f $package_dir/$filename ]] && (( fm > local_major || (fm == local_major && fn > local_minor) )); then
        local_selected=$filename; local_sha=$sha; local_major=$fm; local_minor=$fn
    fi
    if (( fm > best_major || (fm == best_major && fn > best_minor) )); then
        selected=$filename; expected=$sha; best_major=$fm; best_minor=$fn
    fi
done < "$work/components.tsv"
if [[ -n $local_selected ]]; then selected=$local_selected; expected=$local_sha; best_major=$local_major; best_minor=$local_minor; fi
if (( offline )) && [[ -z $local_selected ]]; then echo 'No compatible local core archive; copy one listed in components.tsv.' >&2; exit 1; fi
[[ -n $selected ]] || { echo "No compatible package for Linux $arch / glibc $glibc / this CPU." >&2; exit 1; }
[[ $selected == cosmos-$version-core-linux-$arch-glibc[0-9]*.tar.gz && $selected != */* ]] || { echo 'Invalid manifest filename.' >&2; exit 1; }
printf 'Selected Linux %s / glibc >= %s.%s\n' "$arch" "$best_major" "$best_minor"
fetch "$base/$selected" "$work/$selected"
printf 'Verifying core archive…\n'
(cd "$work" && printf '%s  %s\n' "$expected" "$selected" | sha256sum --check --status)
printf 'Extracting core archive…\n'
tar --no-same-owner --no-same-permissions -xzf "$work/$selected" -C "$work"
installer=$work/${selected%.tar.gz}/install.sh
[[ -f $installer ]] || { echo 'Core archive is missing install.sh.' >&2; exit 1; }
bash "$installer" "$@"
