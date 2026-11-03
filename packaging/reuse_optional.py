"""Restore an unchanged optional component from a public release on cache miss."""
import json
import os
from pathlib import Path
import shutil
import urllib.error
import urllib.request
import urllib.parse

from installer import download, extract

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/WilliamMarci/cosmos'


def reuse(kind, tier):
    if kind not in {'pdf', 'rime'}:
        raise ValueError('Only optional native components may be reused')
    headers = {'User-Agent': 'cosmos-release-builder', 'Accept': 'application/vnd.github+json'}
    token = os.getenv('GH_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request('https://api.github.com/repos/WilliamMarci/cosmos/releases?per_page=20', headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        releases = json.load(response)
    work = ROOT / '.build' / ('optional-' + kind)
    work.mkdir(parents=True, exist_ok=True)
    for release in releases:
        if release['draft'] or not release.get('published_at'):
            continue
        tag = release['tag_name']
        # The native recipe and ABI collector must match byte for byte.
        matched = True
        for name in ('build_optional.sh', 'assemble.py'):
            url = 'https://raw.githubusercontent.com/WilliamMarci/cosmos/' + urllib.parse.quote(tag, safe='') + '/packaging/' + name
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    if response.read(1024**2) != (ROOT / 'packaging' / name).read_bytes():
                        matched = False
                        break
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    matched = False
                    break
                raise
        if not matched:
            continue
        base = REPO + '/releases/download/' + tag
        manifest_path = work / 'previous-components.json'
        try:
            download(base + '/components.json', manifest_path, 128 * 1024)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        manifest = json.loads(manifest_path.read_text())
        entry = next((e for e in manifest['components'] if e['name'] == kind and e['arch'] == 'x86_64' and e['glibc_min'] == tier), None)
        if not entry:
            continue
        filename = entry['filename']
        if Path(filename).name != filename or entry['url'] != base + '/' + filename:
            raise ValueError('Invalid previous release component URL')
        archive = work / filename
        download(entry['url'], archive, entry['size'])
        import hashlib
        with archive.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != entry['sha256'] or archive.stat().st_size != entry['size']:
            raise ValueError('Previous component checksum/size mismatch')
        source_name = f"cosmos-{manifest['version']}-{kind}-glibc{tier}-sources.tar.gz"
        checksum = work / 'source.sha256'
        download(base + '/' + source_name + '.sha256', checksum, 1024)
        expected, recorded = checksum.read_text().strip().split('  ', 1)
        if recorded != source_name:
            raise ValueError('Previous source checksum filename mismatch')
        sources = work / 'corresponding-sources.tar.gz'
        download(base + '/' + source_name, sources, 512 * 1024**2)
        with sources.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != expected:
            raise ValueError('Previous source checksum mismatch')
        stage = work / 'stage'
        shutil.rmtree(stage, ignore_errors=True)
        extract(archive, stage, entry['unpacked_size'])
        archive.unlink()
        print(f'Reusing {kind} / glibc {tier} from {tag}; native recipe unchanged', flush=True)
        return True
    return False


if __name__ == '__main__':
    import sys
    restored = reuse(sys.argv[1], os.environ['COSMOS_GLIBC_TIER'])
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('restored=' + str(restored).lower() + '\n')
