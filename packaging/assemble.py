"""Assemble size-bounded release components; never copy developer caches."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = runpy.run_path(str(ROOT / "python/cosmos_tui/core/metadata.py"))["VERSION"]
DIST = ROOT / "dist"


def copy(source, destination):
    if source.resolve() == destination.resolve():
        return
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"), dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def closure(binary, destination):
    """Copy only non-glibc ELF dependencies, dereferencing SONAME symlinks."""
    output = subprocess.check_output(["ldd", str(binary)], text=True)
    for line in output.splitlines():
        if "=> not found" in line:
            raise RuntimeError("Missing library for " + str(binary) + ": " + line)
        if "=> /" not in line:
            continue
        name, rest = line.strip().split(" => ", 1)
        if name.startswith(("libc.so", "libm.so", "libpthread.so", "libdl.so", "librt.so", "libutil.so", "libresolv.so")):
            continue
        path = Path(rest.split(" (", 1)[0])
        copy(path.resolve(), destination / name)
        owner = subprocess.run(["rpm", "-qf", str(path.resolve()), "--qf", "%{NAME}"], text=True, capture_output=True)
        if owner.returncode == 0:
            notices = Path("/usr/share/licenses") / owner.stdout
            if notices.is_dir():
                copy(notices, destination.parent / "licenses" / owner.stdout)


def archive(stage, name, rooted=False):
    DIST.mkdir(exist_ok=True)
    target = DIST / (name + ".tar.gz")
    with tarfile.open(target, "w:gz", compresslevel=9, dereference=False) as tar:
        if rooted:
            tar.add(stage, arcname=name)
        else:
            for path in sorted(stage.iterdir()):
                tar.add(path, arcname=path.name)
    with target.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    target.with_name(target.name + ".sha256").write_text(digest + "  " + target.name + "\n")
    print(target)


def check_abi(binary, maximum="2.28"):
    import re
    output = subprocess.check_output(["readelf", "--version-info", str(binary)], text=True)
    versions = [tuple(map(int, value.split("."))) for value in re.findall(r"GLIBC_([0-9.]+)", output)]
    if versions and max(versions) > tuple(map(int, maximum.split("."))):
        raise RuntimeError(f"{binary} needs glibc {'.'.join(map(str, max(versions)))}; build this tier on AlmaLinux 8")


def main(kind, source):
    stage = ROOT / ".build" / ("release-stage-" + kind)
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    if kind == "core":
        for name in ("python/cosmos_tui", "terminal_agent/terminal_agent", "terminal_agent/shell", "terminal_agent/native", "shell", "config", "themes", "mods", "skills", "docs", "sdk/python"):
            copy(ROOT / name, stage / name)
        for name in ("cosmos", "README.md", "RELEASE.md", "LICENSE"):
            copy(ROOT / name, stage / name)
        copy(ROOT / "packaging/install.sh", stage / "install.sh")
        copy(ROOT / "packaging/installer.py", stage / "installer.py")
        copy(ROOT / "packaging/requirements.lock", stage / "python/requirements.lock")
        copy(ROOT / "target/release/cosmos", stage / "bin/cosmos")
        copy(ROOT / ".build/libcosmos_files.so", stage / ".build/libcosmos_files.so")
        copy(ROOT / ".build/release-native/terminal-agent-readline.so", stage / "terminal_agent/.build/terminal-agent-readline.so")
        copy(source, stage / "runtime")
        copy(ROOT / ".build/release-deps", stage / "python-deps")
        # Tests, pip and developer headers are not needed by a runtime venv.
        for relative in ("runtime/include", "runtime/lib/python3.12/test", "runtime/lib/python3.12/ensurepip"):
            shutil.rmtree(stage / relative, ignore_errors=True)
        tmux = ROOT / ".build/tmux-install/bin/tmux"
        copy(tmux, stage / "bin/tmux")
        closure(tmux, stage / "lib")
        closure(stage / "bin/cosmos", stage / "lib")
        closure(stage / ".build/libcosmos_files.so", stage / "lib")
        copy(ROOT / "packaging/notices", stage / "licenses/integrations")
        copy(ROOT / "native/files/LICENSE-Yazi", stage / "licenses/integrations/Yazi-MIT.txt")
        subprocess.run([sys.executable, str(ROOT / "packaging/licenses.py"), str(stage / "licenses/rust")], check=True)
        # Each wheel retains its dist-info license files and METADATA.
        (stage / "licenses/PYTHON.txt").write_text("Python runtime license: runtime/LICENSE*; Python wheel licenses and provenance: python-deps/*.dist-info/. Bundled tmux license: licenses/tmux-COPYING.\n")
        tmux_notice = ROOT / ".build/tmux-source/COPYING"
        if tmux_notice.exists():
            copy(tmux_notice, stage / "licenses/tmux-COPYING")
        else:
            raise RuntimeError("Missing tmux copyright notice")
        glibc = "2.28"
        # Reject accidentally building a public compatibility tier on a newer host.
        for binary in [stage / "bin/cosmos", stage / "bin/tmux", stage / ".build/libcosmos_files.so", stage / "terminal_agent/.build/terminal-agent-readline.so"]:
            check_abi(binary, glibc)
        (stage / "bundle.json").write_text(json.dumps(dict(version=VERSION, platform="linux-x86_64", glibc=glibc, cpu_flags=["sse4_1", "sse4_2", "ssse3", "popcnt", "cx16", "lahf_lm"], python="3.12", features=["core", "assistant"]), indent=2) + "\n")
        checksums = []
        for path in sorted(stage.rglob("*")):
            if path.is_file() and not path.is_symlink():
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                checksums.append(digest + "  " + str(path.relative_to(stage)))
        (stage / "SHA256SUMS").write_text("\n".join(checksums) + "\n")
    else:
        copy(source, stage)
    archive(stage, f"cosmos-{VERSION}-{kind}-linux-x86_64-glibc2.28", rooted=kind == "core")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
