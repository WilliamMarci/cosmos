"""Build-only ELF isolation: private lookup paths, without runtime LD_* exports."""
from pathlib import Path
import os
import subprocess


def patch_private_elfs(stage):
    stage = Path(stage)
    for path in stage.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open('rb') as stream:
            header = stream.read(20)
        if header[:4] != b'\x7fELF' or len(header) < 20:
            continue
        endian = 'little' if header[5] == 1 else 'big'
        if int.from_bytes(header[16:18], endian) not in (2, 3):
            continue
        # Bun's embedded executable is not rewritten; it has no private closure.
        if path.name == 'cosmos-agent':
            continue
        old = subprocess.check_output(['patchelf', '--print-rpath', str(path)], text=True).strip()
        paths = ['$ORIGIN'] + [p for p in old.split(':') if p.startswith('$ORIGIN')]
        for parent in (path.parent, *path.parent.parents):
            if not parent.is_relative_to(stage):
                break
            library = parent / 'lib'
            if library.is_dir():
                relative = os.path.relpath(library, path.parent)
                paths.append('$ORIGIN' if relative == '.' else '$ORIGIN/' + relative)
        if path.is_relative_to(stage / 'python-deps') and (stage / 'lib').is_dir():
            # Wheels move three directory levels deeper when installed in the
            # private venv. Support both the transport and installed layouts.
            installed = stage / '.venv/lib/python3.12/site-packages' / path.relative_to(stage / 'python-deps')
            paths.append('$ORIGIN/' + os.path.relpath(stage / 'lib', installed.parent))
        # DT_RPATH keeps host Conda/ROOT paths from overriding bundled dependencies.
        subprocess.run(['patchelf', '--force-rpath', '--set-rpath', ':'.join(dict.fromkeys(paths)), str(path)], check=True)
