#!/usr/bin/env bash
# Optional single-file entry: select -> download -> checksum -> extract -> TUI.
set -euo pipefail
version=0.2.2
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Cosmos installer bootstrap: requires Linux, Bash, curl/wget, tar, sha256sum, getconf.'
    echo 'Downloads the highest compatible core from the release manifest, then opens the multi-select installer.'
    echo 'Arguments are forwarded: --prefix DIR --bin-dir DIR --features LIST --yes --check'
    exit 0
fi
[[ $(uname -s) == Linux ]] || { echo 'No compatible package: Linux is required.' >&2; exit 1; }
for tool in tar sha256sum getconf grep mktemp; do
    command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done
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
    if command -v curl >/dev/null; then
        curl --fail --location --proto '=https' --tlsv1.2 --retry 2 --max-time 600 --output "$2" "$1"
    elif command -v wget >/dev/null; then
        wget --https-only --timeout=60 --tries=2 -O "$2" "$1"
    else
        echo 'curl or wget is required; alternatively download/extract a core archive manually.' >&2; exit 1
    fi
}
base=https://github.com/WilliamMarci/cosmos/releases/download/v$version
fetch "$base/components.tsv" "$work/components.tsv"
best_major=-1; best_minor=-1; selected=''
while IFS=$'\t' read -r name v a floor flags filename url sha size unpacked; do
    [[ $name == core && $v == "$version" && $a == "$arch" ]] || continue
    [[ $floor =~ ^[0-9]+\.[0-9]+$ && $sha =~ ^[0-9a-f]{64}$ ]] || continue
    fm=${floor%%.*}; fn=${floor#*.}
    (( fm < major || (fm == major && fn <= minor) )) || continue
    compatible=1
    IFS=, read -ra required <<< "$flags"
    for flag in "${required[@]}"; do grep -qw -- "$flag" /proc/cpuinfo || compatible=0; done
    (( compatible )) || continue
    if (( fm > best_major || (fm == best_major && fn > best_minor) )); then
        selected=$filename; expected=$sha; best_major=$fm; best_minor=$fn
    fi
done < "$work/components.tsv"
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
