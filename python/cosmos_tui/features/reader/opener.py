"""Cosmos-aware open: supported local files in the pane; others via desktop."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    binary = os.environ.get("COSMOS_BINARY", "cosmos")
    result = 0
    for value in args.paths:
        # URLs retain their scheme; filenames become absolute so leading '-' is safe.
        remote = "://" in value or value.startswith("mailto:")
        path = Path(value).expanduser().absolute() if not remote else None
        integrated = bool(os.getenv("TMUX_PANE") and os.getenv("TMUX"))
        supported = (
            path is not None and path.is_file() and path.suffix.lower() in SUPPORTED
        )
        command = (
            [binary, "open", str(path)]
            if integrated and supported
            else ["xdg-open", str(path) if path else value]
        )
        try:
            status = subprocess.call(command)
        except OSError as error:
            print(f"open: {error}", file=sys.stderr)
            status = 1
        result = result or status
    return result


if __name__ == "__main__":
    sys.exit(main())
