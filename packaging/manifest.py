"""Create the published compatibility/size/hash manifest from finished archives."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tarfile

root = Path(__file__).resolve().parents[1]
version = runpy.run_path(str(root / "python/cosmos_tui/core/metadata.py"))["VERSION"]
entries = []
for name in ("core", "agent", "pdf", "rime"):
    filename = f"cosmos-{version}-{name}-linux-x86_64-glibc2.28.tar.gz"
    path = root / "dist" / filename
    with path.open("rb") as file:
        sha = hashlib.file_digest(file, "sha256").hexdigest()
    with tarfile.open(path) as tar:
        size = sum(item.size for item in tar.getmembers() if item.isfile())
    entries.append(dict(name=name, version=version, arch="x86_64", os="linux", glibc_min="2.28", cpu_flags=["sse4_1", "sse4_2", "ssse3", "popcnt", "cx16", "lahf_lm"], filename=filename, size=path.stat().st_size, unpacked_size=size, url=f"https://github.com/WilliamMarci/cosmos/releases/download/v{version}/{filename}", sha256=sha))
manifest = dict(schema=1, version=version, source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), components=entries)
(root / "dist/components.json").write_text(json.dumps(manifest, indent=2) + "\n")
