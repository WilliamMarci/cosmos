"""Collect cached dependency license notices for the foundation archive."""
import os
from pathlib import Path
import shutil
import sys
import tomllib

root = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1])
registry = Path(os.environ.get('CARGO_HOME', Path.home() / '.cargo')) / 'registry/src'
manifest = tomllib.loads((root / 'Cargo.lock').read_text())
notices = []
for package in manifest['package']:
    if 'source' not in package:
        continue
    name = f"{package['name']}-{package['version']}"
    sources = list(registry.glob(f'*/{name}'))
    if len(sources) != 1:
        raise RuntimeError(f'Cannot locate cached license for {name}')
    source = sources[0]
    metadata = tomllib.loads((source / 'Cargo.toml').read_text())['package']
    license_files = list(source.glob('LICENSE*')) + list(source.glob('COPYING*'))
    if metadata.get('license-file'):
        license_files.append(source / metadata['license-file'])
    if not license_files:
        raise RuntimeError(f'No license file found for {name}')
    destination = target / name
    destination.mkdir(parents=True, exist_ok=True)
    for file in set(license_files):
        if file.is_file():
            shutil.copy2(file, destination / file.name)
    notices.append(f"{name}: {metadata.get('license', 'see included license file')}")
target.mkdir(parents=True, exist_ok=True)
for notice in (root / 'packaging/notices').glob('*.txt'):
    shutil.copy2(notice, target / notice.name)
    notices.append(f"{notice.name}: upstream notice for adapted integration code")
(target / 'DEPENDENCIES.txt').write_text('\n'.join(notices) + '\n')
