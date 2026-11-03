"""Create compatibility/size/hash manifests from finished release archives."""
import hashlib
import json
from pathlib import Path
import runpy
import re
import subprocess
import tarfile

from installer import payload_digest

root = Path(__file__).resolve().parents[1]
version = runpy.run_path(str(root / "python/cosmos_tui/core/metadata.py"))["VERSION"]
entries = []
flags = ["sse4_1", "sse4_2", "ssse3", "popcnt", "cx16", "lahf_lm"]
for tier in ("2.28", "2.34"):
    for name in ("core", "agent", "pdf", "rime"):
        filename = f"cosmos-{version}-{name}-linux-x86_64-glibc{tier}.tar.gz"
        path = root / "dist" / filename
        with path.open("rb") as file:
            sha = hashlib.file_digest(file, "sha256").hexdigest()
        with tarfile.open(path) as tar:
            size = sum(item.size for item in tar.getmembers() if item.isfile())
        records = []
        if name != "core":
            with tarfile.open(path) as tar:
                for item in tar:
                    if item.isfile():
                        with tar.extractfile(item) as stream:
                            records.append((Path(item.name).as_posix(), item.mode & 0o777, hashlib.file_digest(stream, "sha256").hexdigest()))
        entries.append(dict(name=name, version=version, arch="x86_64", os="linux", glibc_min=tier, cpu_flags=flags, filename=filename, size=path.stat().st_size, unpacked_size=size, url=f"https://github.com/WilliamMarci/cosmos/releases/download/v{version}/{filename}", sha256=sha, **({"payload_sha256": payload_digest(records)} if records else {})))
for path in sorted((root / "dist").glob("*-sources.tar.gz")):
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    path.with_name(path.name + ".sha256").write_text(digest + "  " + path.name + "\n")
manifest = dict(schema=1, version=version, source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), components=entries)
(root / "dist/components.json").write_text(json.dumps(manifest, indent=2) + "\n")
# Same records for a dependency-free Bash bootstrap; no JSON parser is required.
lines = ["\t".join(str(item[key]) if key != "cpu_flags" else ",".join(item[key]) for key in ("name", "version", "arch", "glibc_min", "cpu_flags", "filename", "url", "sha256", "size", "unpacked_size")) for item in entries]
(root / "dist/components.tsv").write_text("\n".join(lines) + "\n")

bootstrap = (root / "packaging/bootstrap.sh").read_text()
bootstrap, count = re.subn(r"(?m)^version=.*$", "version=" + version, bootstrap, count=1)
if count != 1:
    raise RuntimeError("Bootstrap version field missing")
(root / "dist/install.sh").write_text(bootstrap)
(root / "dist/install.sh").chmod(0o755)
