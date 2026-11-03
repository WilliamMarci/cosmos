"""GitHub release updates through the same verified user-space installer."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

from cosmos_tui.core.paths import PROJECT_ROOT

REPOSITORY = "https://github.com/WilliamMarci/cosmos"


def installer_module():
    path = PROJECT_ROOT / "installer.py"
    if not path.is_file():
        path = PROJECT_ROOT / "packaging/installer.py"
    spec = importlib.util.spec_from_file_location("cosmos_release_installer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_version(releases):
    versions = []
    for release in releases:
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", release.get("tag_name", ""))
        if match and not release.get("draft") and release.get("published_at"):
            versions.append(tuple(map(int, match.groups())))
    if not versions:
        raise ValueError("No published compatible Cosmos release found")
    return ".".join(map(str, max(versions)))


def next_prefix(current, old, new):
    if current.name.endswith(old):
        return current.with_name(current.name[:-len(old)] + new)
    return current.with_name(current.name + "-" + new)


def update(*, bin_dir=None):
    installed = PROJECT_ROOT / "installed-features.json"
    if not installed.is_file():
        raise ValueError("cosmos update requires a release installation; update a source checkout with Git")
    metadata = json.loads(installed.read_text())
    installer = installer_module()
    cache = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache")) / "cosmos"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="update-", dir=cache) as folder:
        work = Path(folder)
        releases = work / "releases.json"
        installer.download("https://api.github.com/repos/WilliamMarci/cosmos/releases?per_page=20", releases, 1024**2)
        version = release_version(json.loads(releases.read_text()))
        if tuple(map(int, version.split("."))) <= tuple(map(int, metadata["version"].split("."))):
            print("Cosmos " + metadata["version"] + " is already up to date")
            return
        bindir = Path(bin_dir or metadata.get("bin_dir", Path.home() / ".local/bin")).expanduser().absolute()
        entry = bindir / "cosmos"
        if not entry.is_symlink() or entry.resolve() != (PROJECT_ROOT / "cosmos").resolve():
            raise ValueError("Cannot identify this installation's command entry; specify --bin-dir")
        prefix = next_prefix(PROJECT_ROOT, metadata["version"], version)
        if prefix.exists() or prefix.is_symlink():
            raise ValueError("Update destination already exists: " + str(prefix))
        print(f"Update Cosmos {metadata['version']} → {version}", flush=True)
        base = REPOSITORY + "/releases/download/v" + version
        manifest_path = work / "components.json"
        installer.download(base + "/components.json", manifest_path, 128 * 1024)
        manifest = json.loads(manifest_path.read_text())
        if manifest["version"] != version:
            raise ValueError("Update manifest version mismatch")
        glibc = tuple(map(int, os.confstr("CS_GNU_LIBC_VERSION").split()[-1].split(".")))
        processors = [set(line.partition(":")[2].split()) for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("flags")]
        flags = set.intersection(*processors) if processors else set()
        core = installer.select_component(manifest, "core", os.uname().machine, glibc, flags)
        filename = core["filename"]
        if Path(filename).name != filename or core["url"] != base + "/" + filename or not 0 < core["size"] <= 1024**3:
            raise ValueError("Invalid core download manifest")
        archive = work / filename
        installer.download(core["url"], archive, core["size"])
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if archive.stat().st_size != core["size"] or digest != core["sha256"]:
            raise ValueError("Update core checksum/size mismatch")
        bundle = work / filename.removesuffix(".tar.gz")
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            if any(not Path(m.name).parts or Path(m.name).parts[0] != bundle.name or ".." in Path(m.name).parts for m in members):
                raise ValueError("Unsafe update archive root")
            required = sum(m.size for m in members)
            if shutil.disk_usage(work).free < required:
                raise ValueError("Insufficient update extraction space")
            if required > 2 * 1024**3:
                raise ValueError("Update core exceeds extraction budget")
            # data filter rejects escaping links and paths; verify() checks files next.
            tar.extractall(work, filter="data")
        if not (bundle / "install.sh").is_file():
            raise ValueError("Update core is missing installer")
        (bundle / "components.json").write_text(json.dumps(manifest))
        subprocess.run([str(bundle / "runtime/bin/python3"), "-I", str(bundle / "installer.py"), "--bundle", str(bundle), "--yes", "--features", ",".join(metadata["features"]), "--prefix", str(prefix), "--bin-dir", str(bindir), "--reuse-from", str(PROJECT_ROOT)], check=True)
        print("Updated successfully. Existing sessions keep running; stop the previous coordinator before reopening Cosmos.")
