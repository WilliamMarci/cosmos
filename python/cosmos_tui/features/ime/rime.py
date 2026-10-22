"""Small ctypes adapter for librime's versioned C API (integer Bool ABI)."""

import ctypes as C
from ctypes.util import find_library
import os
import fcntl
import hashlib
import sysconfig
from pathlib import Path

from cosmos_tui.core.paths import PROJECT_ROOT
from cosmos_tui.features.ime.config import configuration


class Traits(C.Structure):
    _fields_ = (
        [("data_size", C.c_int)]
        + [
            (name, C.c_char_p)
            for name in (
                "shared_data_dir",
                "user_data_dir",
                "distribution_name",
                "distribution_code_name",
                "distribution_version",
                "app_name",
            )
        ]
        + [("modules", C.c_void_p), ("min_log_level", C.c_int)]
        + [
            (name, C.c_char_p)
            for name in ("log_dir", "prebuilt_data_dir", "staging_dir")
        ]
    )


class Composition(C.Structure):
    _fields_ = [
        (name, C.c_int) for name in ("length", "cursor_pos", "sel_start", "sel_end")
    ] + [("preedit", C.c_char_p)]


class Candidate(C.Structure):
    _fields_ = [("text", C.c_char_p), ("comment", C.c_char_p), ("reserved", C.c_void_p)]


class Menu(C.Structure):
    _fields_ = [
        (name, C.c_int)
        for name in (
            "page_size",
            "page_no",
            "is_last_page",
            "highlighted_candidate_index",
            "num_candidates",
        )
    ] + [("candidates", C.POINTER(Candidate)), ("select_keys", C.c_char_p)]


class Context(C.Structure):
    _fields_ = [
        ("data_size", C.c_int),
        ("composition", Composition),
        ("menu", Menu),
        ("commit_text_preview", C.c_char_p),
        ("select_labels", C.POINTER(C.c_char_p)),
    ]


class Commit(C.Structure):
    _fields_ = [("data_size", C.c_int), ("text", C.c_char_p)]


FUNCTIONS = """setup set_notification_handler initialize finalize start_maintenance is_maintenance_mode join_maintenance_thread deployer_initialize prebuild deploy deploy_schema deploy_config_file sync_user_data create_session find_session destroy_session cleanup_stale_sessions cleanup_all_sessions process_key commit_composition clear_composition get_commit free_commit get_context free_context get_status free_status set_option get_option set_property get_property get_schema_list free_schema_list get_current_schema select_schema""".split()


class API(C.Structure):
    _fields_ = [("data_size", C.c_int)] + [(name, C.c_void_p) for name in FUNCTIONS]


def sized(structure):
    result = structure()
    result.data_size = C.sizeof(structure) - C.sizeof(C.c_int)
    return result


def decode(value):
    return value.decode("utf-8", errors="replace") if value else ""


class Rime:
    def __init__(self):
        bundled = PROJECT_ROOT / "lib/librime.so.1"
        library = os.getenv("COSMOS_RIME_LIBRARY") or (
            str(bundled) if bundled.exists() else find_library("rime")
        )
        if not library:
            raise RuntimeError(
                "Rime is unavailable; install librime or set COSMOS_RIME_LIBRARY"
            )
        self.library = C.CDLL(library, mode=C.RTLD_GLOBAL)
        plugin_dir = Path(
            os.getenv("COSMOS_RIME_PLUGINS", str(PROJECT_ROOT / "lib/rime-plugins"))
        )
        if not plugin_dir.is_dir():
            plugin_dir = (
                Path("/usr/lib")
                / sysconfig.get_config_var("MULTIARCH")
                / "rime-plugins"
            )
        self.plugins = [
            C.CDLL(str(path), mode=C.RTLD_GLOBAL)
            for path in sorted(plugin_dir.glob("librime-*.so"))
        ]

        self.library.rime_get_api.restype = C.POINTER(API)
        self.api = self.library.rime_get_api().contents
        if self.api.data_size + 4 < C.sizeof(API):
            raise RuntimeError("librime C API is too old")
        self.sessions = {}
        source, self.schema = configuration()
        state = (
            Path(os.getenv("XDG_STATE_HOME", str(Path.home() / ".local/state")))
            / "cosmos/rime"
        )
        state.mkdir(parents=True, exist_ok=True)
        resources = (
            state
            / "resources"
            / hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:16]
        )
        resources.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            if (
                ".userdb" in item.name
                or item.name in {"user.yaml", "installation.yaml", "sync"}
                or ".log" in item.name
            ):
                continue
            destination = resources / item.name
            if not destination.exists() and not destination.is_symlink():
                try:
                    destination.symlink_to(item)
                except FileExistsError:
                    pass
        for slot in range(100):
            user = state / "profiles" / str(slot)
            user.mkdir(parents=True, exist_ok=True)
            lock = (user / ".lock").open("a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.lock = lock
                break
            except BlockingIOError:
                lock.close()
        else:
            raise RuntimeError("No free Cosmos Rime profile")
        source = resources
        self.traits = sized(Traits)
        for name, value in dict(
            shared_data_dir=source,
            user_data_dir=user,
            distribution_name="Cosmos",
            distribution_code_name="cosmos",
            distribution_version="0.1.0",
            app_name="rime.cosmos",
            log_dir=state,
            prebuilt_data_dir=source / "build",
            staging_dir=user / "build",
        ).items():
            setattr(self.traits, name, str(value).encode())
        self.traits.min_log_level = 2
        self.call("setup", None, [C.POINTER(Traits)], C.byref(self.traits))
        self.call("initialize", None, [C.POINTER(Traits)], C.byref(self.traits))

    def call(self, name, result, types, *arguments):
        return C.CFUNCTYPE(result, *types)(getattr(self.api, name))(*arguments)

    def session(self, target, full=False):
        if target not in self.sessions:
            sid = self.call("create_session", C.c_size_t, [])
            if not sid:
                raise RuntimeError("Could not create Rime session")
            if not self.call(
                "select_schema",
                C.c_int,
                [C.c_size_t, C.c_char_p],
                sid,
                self.schema.encode(),
            ):
                self.call("destroy_session", C.c_int, [C.c_size_t], sid)
                raise RuntimeError(
                    f"Could not load {self.schema}; check Rime data and plugins"
                )
            self.sessions[target] = sid
        sid = self.sessions[target]
        self.call(
            "set_option", None, [C.c_size_t, C.c_char_p, C.c_int], sid, b"ascii_mode", 0
        )
        self.call(
            "set_option",
            None,
            [C.c_size_t, C.c_char_p, C.c_int],
            sid,
            b"full_shape",
            full,
        )
        return sid

    def process(self, target, key, full=False):
        sid = self.session(target, full)
        handled = bool(
            self.call(
                "process_key", C.c_int, [C.c_size_t, C.c_int, C.c_int], sid, key, 0
            )
        )
        commit = sized(Commit)
        text = ""
        if self.call(
            "get_commit", C.c_int, [C.c_size_t, C.POINTER(Commit)], sid, C.byref(commit)
        ):
            try:
                text = decode(commit.text)
            finally:
                self.call("free_commit", C.c_int, [C.POINTER(Commit)], C.byref(commit))
        return handled, text

    def context(self, target):
        sid = self.sessions.get(target)
        if sid is None:
            return dict(preedit="", candidates=[], selected=0, page=0)
        ctx = sized(Context)
        if not self.call(
            "get_context", C.c_int, [C.c_size_t, C.POINTER(Context)], sid, C.byref(ctx)
        ):
            return dict(preedit="", candidates=[], selected=0, page=0)
        try:
            return dict(
                preedit=decode(ctx.composition.preedit),
                cursor=len(
                    decode(
                        (ctx.composition.preedit or b"")[: ctx.composition.cursor_pos]
                    )
                ),
                selection=(
                    len(
                        decode(
                            (ctx.composition.preedit or b"")[
                                : ctx.composition.sel_start
                            ]
                        )
                    ),
                    len(
                        decode(
                            (ctx.composition.preedit or b"")[: ctx.composition.sel_end]
                        )
                    ),
                ),
                last_page=bool(ctx.menu.is_last_page),
                candidates=[
                    decode(ctx.menu.candidates[i].text)
                    for i in range(ctx.menu.num_candidates)
                ],
                selected=ctx.menu.highlighted_candidate_index,
                page=ctx.menu.page_no,
            )
        finally:
            self.call("free_context", C.c_int, [C.POINTER(Context)], C.byref(ctx))

    def close(self):
        for sid in self.sessions.values():
            self.call("destroy_session", C.c_int, [C.c_size_t], sid)
        self.sessions.clear()
        self.call("finalize", None, [])
        self.lock.close()
