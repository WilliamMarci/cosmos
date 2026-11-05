"""User-only, relocatable installation of a verified Cosmos release bundle."""
import argparse
import ctypes
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tarfile
import tempfile
import sys
import time
import urllib.request
import urllib.error

FEATURES = {"core", "agent", "assistant", "pdf", "rime"}


class Progress:
    """Plain progress lines work equally in SSH terminals and redirected logs."""
    def __init__(self, label, total=0):
        self.label, self.total, self.done = label, total, 0
        self.last, self.percent = 0.0, -1
        self.show(force=True)

    def advance(self, amount):
        self.done += amount
        self.show()

    def show(self, force=False):
        percent = min(100, int(100 * self.done / self.total)) if self.total else None
        now = time.monotonic()
        if not force and (now - self.last < 0.25 or (percent is not None and percent // 10 == self.percent // 10)):
            return
        self.last, self.percent = now, percent if percent is not None else -1
        def size(value):
            return f"{value / 1024**2:.1f} MiB" if value >= 1024**2 else f"{value / 1024:.1f} KiB"
        detail = size(self.done)
        if self.total:
            detail += f" / {size(self.total)} ({percent}%)"
        print(f"{self.label}: {detail}", file=sys.stderr, flush=True)

    def finish(self):
        self.show(force=True)
        print(self.label + ": done", file=sys.stderr, flush=True)


def verify(folder):
    lines = (folder / "SHA256SUMS").read_text().splitlines()
    for line in lines:
        path = folder / line.split("  ", 1)[1]
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError("Unsafe checksum path")
    progress = Progress("Verify core", sum((folder / line.split("  ", 1)[1]).stat().st_size for line in lines))
    for line in lines:
        checksum, name = line.split("  ", 1)
        path = folder / name
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError("Unsafe checksum path")
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != checksum:
                raise ValueError("Checksum mismatch: " + name)
        progress.advance(path.stat().st_size)
    progress.finish()


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
            if item.isfile() and path.exists():
                raise ValueError("Component would overwrite an existing file")
        progress = Progress("Extract " + archive.name, sum(item.size for item in members))
        for item in members:
            tar.extract(item, destination, filter="data")
            progress.advance(item.size)
        progress.finish()


def download(url, path, limit, *, attempts=3, timeout=15):
    """Report connection attempts before waiting for headers; never keep partial files."""
    request = urllib.request.Request(url, headers={"User-Agent": "Cosmos-installer"})
    for attempt in range(1, attempts + 1):
        print(f"Connect {attempt}/{attempts}: {url} (connect/read timeout {timeout}s)", file=sys.stderr, flush=True)
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response, path.open("wb") as output:
                length = response.headers.get("Content-Length")
                progress = Progress("Download " + path.name, int(length) if length and length.isdigit() else 0)
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > limit:
                        raise ValueError("Component exceeds download budget")
                    output.write(chunk)
                    progress.advance(len(chunk))
                if length and length.isdigit() and total != int(length):
                    raise OSError("Incomplete download")
                progress.finish()
                return
        except (OSError, urllib.error.URLError) as error:
            path.unlink(missing_ok=True)
            retryable = not isinstance(error, urllib.error.HTTPError) or error.code in {408, 429, 500, 502, 503, 504}
            if not retryable or attempt == attempts:
                raise OSError(f"Download failed: {url}: {error}. Offline: copy components.json and compatible selected archives next to the extracted core's install.sh, then run ./install.sh --offline --package-dir DIR.") from error
            print(f"Connection/download failed: {error}; retrying in {attempt}s", file=sys.stderr, flush=True)
            time.sleep(attempt)
        except ValueError:
            path.unlink(missing_ok=True)
            raise


COMPONENT_ROOTS = {
    "agent": ("bin/cosmos-agent", "licenses/opencode"),
    "pdf": ("vendor/pdf", "licenses/pdf"),
    "rime": ("vendor/rime", "licenses/rime"),
}


def payload_digest(records):
    return hashlib.sha256(json.dumps(sorted(records), separators=(",", ":")).encode()).hexdigest()


def installed_payload(folder, name):
    records, paths = [], []
    for relative in COMPONENT_ROOTS[name]:
        root = folder / relative
        if not root.exists() or root.is_symlink():
            return None, []
        for path in ([root] if root.is_file() else sorted(root.rglob("*"))):
            if path.is_symlink():
                return None, []
            if path.is_file():
                with path.open("rb") as source:
                    digest = hashlib.file_digest(source, "sha256").hexdigest()
                records.append((path.relative_to(folder).as_posix(), path.stat().st_mode & 0o777, digest))
                paths.append(path.relative_to(folder))
    return payload_digest(records), paths


class ReusedComponent:
    def __init__(self, folder, paths):
        self.folder, self.paths = folder, paths


def select_component(manifest, name, arch, glibc, flags, package_dir=None, offline=False):
    matches = [item for item in manifest["components"] if item["name"] == name and item["arch"] == arch
               and tuple(map(int, item["glibc_min"].split("."))) <= glibc
               and set(item["cpu_flags"]).issubset(flags)]
    if not matches:
        raise ValueError("No compatible component: " + name)
    if package_dir:
        local = [item for item in matches if Path(item["filename"]).name == item["filename"] and (package_dir / item["filename"]).is_file()]
        if local:
            matches = local
        elif offline:
            raise ValueError("Offline package missing for " + name + "; copy a compatible archive listed in components.json to " + str(package_dir))
    return max(matches, key=lambda item: tuple(map(int, item["glibc_min"].split("."))))


def component(bundle, name, version, temporary, manifest, reuse_from=None, package_dir=None, offline=False):
    actual_glibc = tuple(map(int, os.confstr("CS_GNU_LIBC_VERSION").split()[-1].split(".")))
    processors = [set(line.partition(":")[2].split()) for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("flags")]
    flags = set.intersection(*processors) if processors else set()
    entry = select_component(manifest, name, os.uname().machine, actual_glibc, flags, package_dir or bundle, False)
    filename = entry["filename"]
    if Path(filename).name != filename or entry["url"] != f"https://github.com/WilliamMarci/cosmos/releases/download/v{version}/{filename}":
        raise ValueError("Invalid component URL or filename")
    if reuse_from and entry.get("payload_sha256"):
        digest, paths = installed_payload(reuse_from, name)
        if digest == entry["payload_sha256"]:
            print("Reuse unchanged component: " + name, file=sys.stderr, flush=True)
            return ReusedComponent(reuse_from, paths), entry
    archive = (package_dir or bundle) / filename
    if not archive.is_file():
        if offline:
            raise ValueError("Offline package missing: " + filename + "; copy it to " + str(package_dir or bundle))
        archive = temporary / filename
        print("Downloading optional component:", name, flush=True)
        download(entry["url"], archive, entry["size"])
    print("Verify component: " + name, file=sys.stderr, flush=True)
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != entry["sha256"] or archive.stat().st_size != entry["size"]:
        raise ValueError("Component checksum/size mismatch: " + name)
    return archive, entry



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--default-features", default="core,agent,assistant")
    parser.add_argument("--features")
    parser.add_argument("--prefix", type=Path)
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--offline", action="store_true", help="never access the network")
    parser.add_argument("--package-dir", type=Path, help="directory containing local manifests and component archives")
    parser.add_argument("--reuse-from", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if os.getuid() == 0:
        parser.error("Run as your normal user; sudo/root installation is not supported")
    bundle = args.bundle.resolve()
    package_dir = (args.package_dir or bundle).expanduser().resolve()
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
            manifest_path = package_dir / "components.json"
            if not manifest_path.exists():
                if args.offline:
                    raise ValueError("Offline manifest missing: " + str(manifest_path) + "; copy components.json from the same release")
                manifest_path = temporary / "components.json"
                download(f"https://github.com/WilliamMarci/cosmos/releases/download/v{version}/components.json", manifest_path, 128 * 1024)
            manifest = json.loads(manifest_path.read_text())
            if manifest["version"] != version:
                raise ValueError("Component manifest version mismatch")
        additions = {name: component(bundle, name, version, temporary, manifest, args.reuse_from, package_dir, args.offline) for name in sorted(selected & {"agent", "pdf", "rime"})}
        prefix.parent.mkdir(parents=True, exist_ok=True)
        # The final path is fixed before venv creation; no relocated shebangs.
        try:
            ignored = ("cosmos-*.tar.gz", "cosmos-*.tar.gz.sha256")
            copy_size = sum(
                p.stat().st_size for p in bundle.rglob("*")
                if p.is_file() and not p.is_symlink()
                and not any(fnmatch.fnmatchcase(p.name, pattern) for pattern in ignored)
                and "__pycache__" not in p.parts
            )
            progress = Progress("Copy core", copy_size)
            def copy_file(source, destination):
                result = shutil.copy2(source, destination)
                progress.advance(Path(source).stat().st_size)
                return result
            shutil.copytree(bundle, prefix, copy_function=copy_file, ignore=shutil.ignore_patterns("cosmos-*.tar.gz", "cosmos-*.tar.gz.sha256", "__pycache__"), symlinks=True)
            progress.finish()
            for name, (archive, component_entry) in additions.items():
                # Extract checked components directly into the new install tree;
                # do not keep a second unpacked copy on a quota-limited server.
                if isinstance(archive, ReusedComponent):
                    progress = Progress(
                        "Copy reused " + name,
                        sum((archive.folder / p).stat().st_size for p in archive.paths),
                    )
                    for relative in archive.paths:
                        destination = prefix / relative
                        if destination.exists() or destination.is_symlink():
                            raise ValueError("Reused component would overwrite a file")
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(archive.folder / relative, destination)
                        progress.advance(destination.stat().st_size)
                    progress.finish()
                    if installed_payload(prefix, name)[0] != component_entry["payload_sha256"]:
                        raise ValueError("Reused component changed during copying: " + name)
                else:
                    extract(archive, prefix, component_entry["unpacked_size"])
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
            print("Configure Python environment and command entry", file=sys.stderr, flush=True)
            python = prefix / "runtime/bin/python3"
            subprocess.run([str(python), "-I", "-m", "venv", "--without-pip", str(prefix / ".venv")], check=True)
            (prefix / "installed-features.json").write_text(json.dumps(dict(version=version, features=sorted(selected), bin_dir=str(bindir)), indent=2) + "\n")
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
