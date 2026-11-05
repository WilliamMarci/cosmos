"""Executable selection and private, PID-reuse-safe backend ownership records."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

from cosmos_tui.core.paths import PROJECT_ROOT


def executable():
    override = os.getenv("COSMOS_TMUX")
    if override:
        return override
    bundled = PROJECT_ROOT / "bin/cosmos-tmux"
    return str(bundled) if bundled.is_file() else "tmux"


def command(socket=None):
    return [executable(), "-L", socket or os.getenv("COSMOS_TMUX_SOCKET", "cosmos")]


def records_dir():
    return Path(os.getenv("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "cosmos/backends"


def identity(pid):
    folder = Path("/proc") / str(int(pid))
    info = (folder / "stat").read_text().rsplit(")", 1)[1].split()
    return dict(pid=int(pid), start=info[19], uid=folder.stat().st_uid, executable=os.readlink(folder / "exe"))


def probe(argv):
    result = subprocess.run([*argv, "display-message", "-p", "#{pid}\t#{socket_path}"], capture_output=True, text=True, timeout=5)
    if result.returncode:
        return None
    pid, socket = result.stdout.strip().split("\t")
    details = identity(pid)
    socket_info = Path(socket).stat()
    if details["uid"] != os.getuid() or socket_info.st_uid != os.getuid() or not stat.S_ISSOCK(socket_info.st_mode):
        raise PermissionError("Backend process/socket belongs to another user")
    return dict(**details, socket=socket)


def record(created_server=False):
    details = probe(command())
    if details is None:
        return
    expected = str(Path(shutil.which(executable()) or executable()).resolve())
    actual = details["executable"].removesuffix(" (deleted)")
    # Adopt only the bundled Cosmos backend, or a server this client just started.
    bundled = (Path(actual).name == "cosmos-tmux" and Path(actual).parent.name == "bin"
               and (Path(actual).parent.parent == PROJECT_ROOT or (Path(actual).parent.parent / "installed-features.json").is_file()))
    legacy = Path(actual).name == "tmux" and (Path(actual).parent.parent / "installed-features.json").is_file()
    if not ((actual == expected and (created_server or bundled)) or legacy):
        return
    folder = records_dir()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.is_symlink() or folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077:
        raise PermissionError("Backend registry must be a private directory owned by this user")
    path = folder / (hashlib.sha256(details["socket"].encode()).hexdigest() + ".json")
    details.update(name=os.getenv("COSMOS_TMUX_SOCKET", "cosmos"), installation=str(PROJECT_ROOT), client=expected)
    fd, temporary = tempfile.mkstemp(dir=folder)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(details, stream)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def verified(path):
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise PermissionError("Untrusted backend record")
    data = json.loads(path.read_text())
    current = probe([executable(), "-S", data["socket"]])
    if current is None:
        return None
    if any(current[key] != data[key] for key in ("pid", "start", "uid", "executable", "socket")):
        raise PermissionError("Backend identity changed; refusing to stop it")
    return data
