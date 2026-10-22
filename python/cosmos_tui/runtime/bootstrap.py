import asyncio
import os
import shlex
import subprocess
from pathlib import Path

from cosmos_tui.core import rpc
from cosmos_tui.core.diagnostics import configure
from cosmos_tui.core.paths import PROJECT_ROOT
from cosmos_tui.ui.farewell import show_farewell


def run(args):
    from cosmos_tui.app import Cosmos

    log_path = configure("DEBUG" if args.debug else args.log_level, args.log_file)
    if args.debug:
        print(f"Cosmos debug log: {log_path}")

    async def ensure():
        try:
            await rpc.call("health")
            return
        except (OSError, RuntimeError):
            pass
        binary = Path(
            os.getenv(
                "COSMOS_BINARY",
                PROJECT_ROOT / "target/release/cosmos",
            )
        )
        process = subprocess.Popen(
            [str(binary), "daemon"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(100):
            try:
                await rpc.call("health")
                return
            except (OSError, RuntimeError):
                if process.poll() is not None:
                    raise RuntimeError(f"coordinator exited: {process.returncode}")
                await asyncio.sleep(0.02)
        process.terminate()
        process.wait(timeout=2)
        raise RuntimeError(
            "coordinator startup failed; run cosmos daemon for diagnostics"
        )

    async def prepare():
        await ensure()
        capabilities = await rpc.call("initialize", {"protocol_major": 1})
        required = {"ui-components-v1", "keybindings"}
        if not required.issubset(capabilities.get("capabilities", [])):
            binary = Path(
                os.getenv(
                    "COSMOS_BINARY",
                    PROJECT_ROOT / "target/release/cosmos",
                )
            )
            entry = PROJECT_ROOT / "cosmos"
            raise RuntimeError(
                "the persistent coordinator lacks required capabilities: "
                + ", ".join(
                    sorted(required - set(capabilities.get("capabilities", [])))
                )
                + ". A new terminal reconnects to the same background service.\n"
                + "Detach other Cosmos clients, then run:\n  "
                + shlex.join([str(binary), "stop"])
                + "\n  "
                + shlex.join(
                    [str(entry), args.session] + (["--debug"] if args.debug else [])
                )
                + "\nTmux applications are retained; coordinator-managed Mods will stop."
            )

    try:
        asyncio.run(prepare())
    except (OSError, RuntimeError, TimeoutError) as error:
        raise RuntimeError(str(error)) from error
    app = Cosmos(args.session, mouse_mode=getattr(args, "mouse_mode", "auto"))
    result = app.run()
    if not app._exception:
        show_farewell(result, app.backend)
