"""Cosmos-aware open: supported local files in the pane; others via desktop."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

SUPPORTED = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".pdf",
    ".epub",
    ".md",
    ".markdown",
    ".html",
    ".htm",
}


def preview(path, bounds, *, media, documents, columns=40, rows=30):
    """Read-only quick-open API; return a Preview without changing pane state."""
    from cosmos_tui.features.reader.preview import preview as render_preview

    return render_preview(
        path, bounds, media=media, documents=documents, columns=columns, rows=rows
    )


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
        if path is not None and path.is_dir():
            from cosmos_tui.features.files.opener import open_directory

            try:
                open_directory(path)
            except (
                OSError,
                RuntimeError,
                ValueError,
                subprocess.CalledProcessError,
            ) as error:
                print(f"open: {error}", file=sys.stderr)
                result = result or 1
            continue
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
