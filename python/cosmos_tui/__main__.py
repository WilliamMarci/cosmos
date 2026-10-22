import argparse
import asyncio
import os
import subprocess
from pathlib import Path
from .app import Cosmos
from . import rpc
from .diagnostics import configure
from .farewell import show_farewell


def main():
    parser = argparse.ArgumentParser(description="Cosmos terminal workspace")
    parser.add_argument("session", nargs="?", default="main")
    parser.add_argument("--debug", action="store_true", help="enable debug log")
    parser.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="WARNING"
    )
    parser.add_argument("--log-file", help="diagnostic log path")
    args = parser.parse_args()
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
                Path(__file__).resolve().parents[2] / "target/release/cosmos",
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
            raise RuntimeError(
                "coordinator is older than this UI; detach clients, then run cosmos stop and start this UI again (Tmux applications are retained)"
            )

    try:
        asyncio.run(prepare())
    except (OSError, RuntimeError, TimeoutError) as error:
        parser.exit(1, f"cosmos: {error}\n")
    app = Cosmos(args.session)
    result = app.run()
    if not app._exception:
        show_farewell(result, app.backend)


if __name__ == "__main__":
    main()
