"""Installer boundaries: integrity, archive traversal and isolated feature choices."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cosmos_installer", ROOT / "packaging/installer.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallationTests(unittest.TestCase):
    def test_checksums_detect_corruption_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / "data").write_bytes(b"safe")
            digest = hashlib.sha256(b"safe").hexdigest()
            (base / "SHA256SUMS").write_text(digest + "  data\n")
            installer.verify(base)
            (base / "data").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                installer.verify(base)
            (base / "SHA256SUMS").write_text(digest + "  ../outside\n")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                installer.verify(base)

    def test_optional_archives_reject_symlinks_and_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for name, symlink in [("../escape", False), ("link", True)]:
                archive = base / "component.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    item = tarfile.TarInfo(name)
                    item.size = 1
                    if symlink:
                        item.type = tarfile.SYMTYPE
                        item.linkname = "/tmp/outside"
                    tar.addfile(item, io.BytesIO(b"x"))
                with self.assertRaisesRegex(ValueError, "Unsafe"):
                    installer.extract(archive, base / "destination")

    def test_feature_selection_is_install_local_and_source_defaults_enabled(self):
        from cosmos_tui.core import features
        with tempfile.TemporaryDirectory() as folder, patch.object(features, "PROJECT_ROOT", Path(folder)):
            self.assertTrue(features.enabled("rime"))
            (Path(folder) / "installed-features.json").write_text(json.dumps(dict(features=["core", "pdf"])))
            self.assertFalse(features.enabled("rime"))
            self.assertTrue(features.enabled("pdf"))

    def test_packager_keeps_already_collected_shared_library(self):
        spec = importlib.util.spec_from_file_location("cosmos_assemble", ROOT / "packaging/assemble.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            library = Path(folder) / "libfixture.so"
            library.write_bytes(b"fixture")
            module.copy(library, library)
            self.assertEqual(library.read_bytes(), b"fixture")

    def test_glibc_tier_selection_rejects_unsupported_cpu_and_architecture(self):
        entries = [dict(name="core", arch="x86_64", glibc_min=tier, cpu_flags=["sse4_2"]) for tier in ("2.28", "2.34")]
        manifest = dict(components=entries)
        self.assertEqual(installer.select_component(manifest, "core", "x86_64", (2, 28), {"sse4_2"})["glibc_min"], "2.28")
        self.assertEqual(installer.select_component(manifest, "core", "x86_64", (2, 34), {"sse4_2"})["glibc_min"], "2.34")
        for arch, glibc, flags in [("aarch64", (2, 34), {"sse4_2"}), ("x86_64", (2, 27), {"sse4_2"}), ("x86_64", (2, 34), set())]:
            with self.assertRaisesRegex(ValueError, "No compatible"):
                installer.select_component(manifest, "core", arch, glibc, flags)
