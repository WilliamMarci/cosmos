#!/usr/bin/env bash
# Developer entry point; never copied into release archives.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
command -v gh >/dev/null || { echo 'Developer dependency required: GitHub CLI (gh)' >&2; exit 1; }
repo=WilliamMarci/cosmos
command=${1:-help}
shift || true
case "$command" in
    build)
        ref=$(git branch --show-current)
        rebuild=false
        while (($#)); do
            case "$1" in
                --ref) ref=${2:?missing ref}; shift 2 ;;
                --rebuild-optional) rebuild=true; shift ;;
                *) echo "Unknown option: $1" >&2; exit 2 ;;
            esac
        done
        git diff --quiet && git diff --cached --quiet || { echo 'Commit tracked changes before building a release.' >&2; exit 1; }
        gh workflow run release.yml --repo "$repo" --ref "$ref" -f rebuild_optional="$rebuild"
        echo "Build dispatched: https://github.com/$repo/actions/workflows/release.yml"
        ;;
    watch)
        gh run watch "${1:?Usage: dev/release.sh watch RUN_ID}" --repo "$repo" --exit-status
        ;;
    publish)
        tag=${1:?Usage: dev/release.sh publish vVERSION}
        command -v python3 >/dev/null || { echo 'Developer dependency required: Python 3' >&2; exit 1; }
        temporary=$(mktemp -d)
        trap 'rm -rf -- "$temporary"' EXIT
        gh release view "$tag" --repo "$repo" --json assets,isDraft > "$temporary/release.json"
        gh release download "$tag" --repo "$repo" --pattern components.json --pattern '*.sha256' --dir "$temporary"
        python3 - "$temporary" <<'PY'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1]); release=json.loads((p/'release.json').read_text())
assert release['isDraft'], 'Release is already published'
assets={a['name']:a for a in release['assets']}
manifest=json.loads((p/'components.json').read_text())
assert {(a['name'],a['glibc_min']) for a in manifest['components']} == {(n,t) for n in ('core','agent','pdf','rime') for t in ('2.28','2.34')}, 'Missing component/tier'
assert {'install.sh','components.json','components.tsv'} <= assets.keys(), 'Missing installer/manifests'
for entry in manifest['components']:
    name=entry['filename']
    assert assets[name]['size']==entry['size'], 'Asset size mismatch: '+name
    assert (p/(name+'.sha256')).read_text().split()==[entry['sha256'],name], 'Checksum manifest mismatch: '+name
print('Release assets and manifest agree. Publish only after target-server acceptance.')
PY
        gh release edit "$tag" --repo "$repo" --draft=false
        ;;
    *)
        echo 'Developer release automation (requires gh authentication):'
        echo '  dev/release.sh build [--ref main] [--rebuild-optional]'
        echo '  dev/release.sh watch RUN_ID'
        echo '  dev/release.sh publish vVERSION   # after target-server acceptance'
        ;;
esac
