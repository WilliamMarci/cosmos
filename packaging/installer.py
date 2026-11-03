"""User-only, relocatable installation of a verified Cosmos release bundle."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tarfile
import tempfile
import urllib.request

FEATURES = {"core", "agent", "assistant", "pdf", "rime"}


def verify(folder):
    for line in (folder / "SHA256SUMS").read_text().splitlines():
        checksum, name = line.split("  ", 1)
        path = folder / name
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError("Unsafe checksum path")
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != checksum:
                raise ValueError("Checksum mismatch: " + name)


def extract(archive, destination, maximum=1024**3):
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if sum(item.size for item in members) > maximum:
            raise ValueError("Unpacked archive exceeds budget")
        for item in members:
            path = destination / item.name
            if not path.resolve().is_relative_to(destination.resolve()) or not (item.isfile() or item.isdir()):
                raise ValueError("Unsafe component archive member: " + item.name)
            if item.mode & 0o7000:
                raise ValueError("Privileged archive member")
        tar.extractall(destination, members=members, filter="data")


def download(url, path, limit):
    request = urllib.request.Request(url, headers={"User-Agent": "Cosmos-installer"})
    with urllib.request.urlopen(request, timeout=60, context=ssl.create_default_context()) as response, path.open("wb") as output:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError("Component exceeds download budget")
            output.write(chunk)


def component(bundle, name, version, temporary, manifest):
    entry = next((item for item in manifest["components"] if item["name"] == name and item["arch"] == "x86_64" and item["glibc_min"] == "2.28"), None)
    if entry is None:
        raise ValueError("No compatible component: " + name)
    filename = entry["filename"]
    if Path(filename).name != filename or entry["url"] != f"https://github.com/WilliamMarci/cosmos/releases/download/v{version}/{filename}":
        raise ValueError("Invalid component URL or filename")
    archive = bundle / filename
    if not archive.is_file():
        archive = temporary / filename
        print("Downloading optional component:", name, flush=True)
        download(entry["url"], archive, entry["size"])
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != entry["sha256"] or archive.stat().st_size != entry["size"]:
        raise ValueError("Component checksum/size mismatch: " + name)
    destination = temporary / name
    destination.mkdir()
    extract(archive, destination, entry["unpacked_size"])
    if sum(p.stat().st_size for p in destination.rglob("*") if p.is_file()) > entry["unpacked_size"]:
        raise ValueError("Component exceeds declared unpacked size")
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--default-features", default="core,agent,assistant")
    parser.add_argument("--features")
    parser.add_argument("--prefix", type=Path)
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if os.getuid() == 0:
        parser.error("Run as your normal user; sudo/root installation is not supported")
    bundle = args.bundle.resolve()
    metadata = json.loads((bundle / "bundle.json").read_text())
    version = metadata["version"]
    actual_glibc = os.confstr("CS_GNU_LIBC_VERSION").split()[-1]
    version_tuple = lambda value: tuple(int(x) for x in value.split("."))
    if version_tuple(actual_glibc) < version_tuple(metadata["glibc"]):
        parser.error("This archive requires glibc " + metadata["glibc"])
    selected = set((args.features or args.default_features).split(",")) | {"core"}
    if selected - FEATURES:
        parser.error("Unknown features: " + ", ".join(sorted(selected - FEATURES)))
    prefix = (args.prefix or Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share")) / "cosmos" / version).expanduser().absolute()
    bindir = args.bin_dir.expanduser().absolute()
    if prefix == bundle or prefix in bundle.parents or bundle in prefix.parents:
        parser.error("Installation directory must be separate from the extracted bundle")
    for path in (prefix, bindir):
        existing = path
        while not existing.exists():
            existing = existing.parent
        if not os.access(existing, os.W_OK):
            parser.error("Directory is not writable: " + str(existing))
    if prefix.exists() or prefix.is_symlink():
        parser.error("Install directory already exists; choose a new --prefix. Existing installations are preserved.")
    entry = bindir / "cosmos"
    if entry.exists() or entry.is_symlink():
        if not entry.is_symlink() or not (entry.resolve().parent / "installed-features.json").is_file():
            parser.error("Refusing to replace an unmanaged command: " + str(entry))
    needed = sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file()) + 1024**3
    disk = prefix.parent
    while not disk.exists():
        disk = disk.parent
    if shutil.disk_usage(disk).free < needed:
        parser.error("Insufficient space (bundle size plus 1 GiB component/setup allowance required)")
    print("Installation:", prefix)
    print("Command:", entry)
    print("Features:", ", ".join(sorted(selected)))
    print("Config/cache/state: XDG user directories; no global environment changes", flush=True)
    verify(bundle)
    subprocess.run([str(bundle / "runtime/bin/python3"), "-I", "-c", "import ssl, sqlite3, ctypes"], check=True)
    subprocess.run([str(bundle / "bin/cosmos"), "--version"], check=True)
    if args.check:
        print("Minimum platform, integrity, permissions and space checks passed.")
        return
    if not args.yes and not args.features:
        if input("Install these choices? [y/N] ").lower() != "y":
            return
    with tempfile.TemporaryDirectory(prefix="cosmos-install-") as temp:
        temporary = Path(temp)
        manifest = {"components": []}
        if selected & {"agent", "pdf", "rime"}:
            manifest_path = bundle / "components.json"
            if not manifest_path.exists():
                manifest_path = temporary / "components.json"
                download(f"https://github.com/WilliamMarci/cosmos/releases/download/v{version}/components.json", manifest_path, 128 * 1024)
            manifest = json.loads(manifest_path.read_text())
            if manifest["version"] != version:
                raise ValueError("Component manifest version mismatch")
        additions = {name: component(bundle, name, version, temporary, manifest) for name in sorted(selected & {"agent", "pdf", "rime"})}
        prefix.parent.mkdir(parents=True, exist_ok=True)
        # The final path is fixed before venv creation; no relocated shebangs.
        try:
            shutil.copytree(bundle, prefix, ignore=shutil.ignore_patterns("cosmos-*.tar.gz", "cosmos-*.tar.gz.sha256", "__pycache__"), symlinks=True)
            for name, folder in additions.items():
                shutil.copytree(folder, prefix, dirs_exist_ok=True)
            if "assistant" not in selected:
                shutil.rmtree(prefix / "terminal_agent/.build", ignore_errors=True)
            for name in selected & {"pdf", "rime"}:
                if name == "pdf":
                    env = {**os.environ, "LD_LIBRARY_PATH": str(prefix / "vendor/pdf/lib")}
                    for executable in ("pdfinfo", "pdftoppm", "pdftotext"):
                        subprocess.run([str(prefix / "vendor/pdf/bin" / executable), "-v"], env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    if not (prefix / "vendor/rime/share/rime-data/build/rime_ice.schema.yaml").is_file():
                        raise ValueError("Compiled rime_ice data missing")
            python = prefix / "runtime/bin/python3"
            subprocess.run([str(python), "-I", "-m", "venv", "--without-pip", str(prefix / ".venv")], check=True)
            (prefix / "installed-features.json").write_text(json.dumps(dict(version=version, features=sorted(selected)), indent=2) + "\n")
            subprocess.run([str(prefix / "cosmos"), "--version"], check=True)
            bindir.mkdir(parents=True, exist_ok=True)
            pending = bindir / (".cosmos-link-" + str(os.getpid()))
            try:
                pending.symlink_to(prefix / "cosmos")
                pending.replace(entry)
            finally:
                pending.unlink(missing_ok=True)
        except BaseException:
            shutil.rmtree(prefix)
            raise
    print("Installed:", entry)
    if str(bindir) not in os.get_exec_path():
        print("This directory is not on PATH; run", entry, "directly (shell startup files were not edited).")
    print("Before switching from an older running coordinator: detach clients, run cosmos stop, then reopen Cosmos.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit("Install failed: " + str(error))
