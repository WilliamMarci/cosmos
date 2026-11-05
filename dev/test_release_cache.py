"""A cached native payload must repackage without invoking build tools."""
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseCacheTests(unittest.TestCase):
    def test_cached_component_repackages_for_new_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'packaging').mkdir()
            for name in ('build_optional.sh', 'assemble.py', 'elf.py'):
                shutil.copy2(ROOT / 'packaging' / name, root / 'packaging' / name)
            metadata = root / 'python/cosmos_tui/core/metadata.py'
            metadata.parent.mkdir(parents=True)
            metadata.write_text('VERSION = "9.8.7"\n')
            work = root / '.build/optional-pdf'
            payload = work / 'stage/vendor/pdf/bin/pdfinfo'
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b'cached native payload')
            source = work / 'corresponding-sources.tar.gz'
            with tarfile.open(source, 'w:gz') as archive:
                archive.add(metadata, arcname='source-fixture.py')
            result = subprocess.run(['bash', str(root / 'packaging/build_optional.sh'), 'pdf'], env={**os.environ, 'COSMOS_GLIBC_TIER': '2.34', 'COSMOS_OPTIONAL_CACHE_HIT': 'true'}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            archive = root / 'dist/cosmos-9.8.7-pdf-linux-x86_64-glibc2.34.tar.gz'
            with tarfile.open(archive) as tar:
                self.assertEqual(tar.extractfile('vendor/pdf/bin/pdfinfo').read(), payload.read_bytes())
            self.assertEqual((root / 'dist/cosmos-9.8.7-pdf-glibc2.34-sources.tar.gz').read_bytes(), source.read_bytes())
            self.assertTrue(archive.with_name(archive.name + '.sha256').is_file())
