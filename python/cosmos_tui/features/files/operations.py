"""Filesystem mutations; no UI and no shell invocation. Never replace targets."""

import os
import errno
from pathlib import Path
import shutil
import stat
import time
from urllib.parse import quote
import uuid


def child(directory, name):
    if not name or name in (".", "..") or "/" in name or "\0" in name:
        raise ValueError("Enter one file name, without a path")
    return Path(directory) / name


def available(path):
    if os.path.lexists(path):
        raise FileExistsError(f"Already exists: {path.name}")


def create(directory, name, folder=False):
    path = child(directory, name)
    if folder:
        path.mkdir()
    else:
        with path.open("xb"):
            pass


def rename(source, name):
    source = Path(source)
    target = child(source.parent, name)
    available(target)
    return _rename_to(source, target)


def _rename_to(source, target):
    # Linux renameat2 provides atomic no-replace even if another writer races us.
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1)
    if result:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


def transfer(sources, directory, move=False):
    destination = Path(directory).resolve(strict=True)
    pairs = [(Path(p), destination / Path(p).name) for p in sources]
    for source, target in pairs:
        source.lstat()
        available(target)
        if (
            source.is_dir()
            and not source.is_symlink()
            and (
                destination == source.resolve()
                or source.resolve() in destination.parents
            )
        ):
            raise ValueError("Cannot place a directory inside itself")
    completed = []
    for source, target in pairs:
        if move:
            try:
                rename(source, target.name) if source.parent == destination else _move(
                    source, target
                )
            except OSError as error:
                raise OSError(
                    f"{len(completed)} completed; {source.name}: {error}"
                ) from error
        elif source.is_symlink():
            target.symlink_to(os.readlink(source))
        elif source.is_dir():
            shutil.copytree(source, target, symlinks=True)
        elif stat.S_ISREG(source.lstat().st_mode):
            with source.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
            shutil.copystat(source, target)
        else:
            raise ValueError("Special files cannot be copied")
        completed.append(str(source))
    return completed


def _move(source, target):
    try:
        _rename_to(source, target)
        return
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
    # Across filesystems, reserve the target before copying.
    if source.is_dir() and not source.is_symlink():
        target.mkdir()
        try:
            # copytree into our exclusively reserved directory, then remove source.
            shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
        except BaseException:
            shutil.rmtree(target)
            raise
        shutil.rmtree(source)
    elif source.is_symlink():
        target.symlink_to(os.readlink(source))
        source.unlink()
    elif stat.S_ISREG(source.lstat().st_mode):
        with source.open("rb") as reader, target.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
        shutil.copystat(source, target)
        source.unlink()
    else:
        raise ValueError("Special files cannot be moved")


def trash(sources):
    root = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share")) / "Trash"
    for sub in ("files", "info"):
        (root / sub).mkdir(parents=True, exist_ok=True, mode=0o700)
    for source in map(Path, sources):
        # absolute() deliberately preserves a symlink itself, rather than its target.
        source = source.absolute()
        name = source.name + "." + uuid.uuid4().hex
        info = root / "info" / (name + ".trashinfo")
        with info.open("x") as stream:
            stream.write(
                "[Trash Info]\nPath="
                + quote(str(source), safe="/")
                + "\nDeletionDate="
                + time.strftime("%Y-%m-%dT%H:%M:%S")
                + "\n"
            )
        try:
            _move(source, root / "files" / name)
        except BaseException:
            if not os.path.lexists(root / "files" / name):
                info.unlink()
            raise
