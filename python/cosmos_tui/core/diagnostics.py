"""Private, bounded diagnostics. Never log terminal text or provider requests."""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure(level="WARNING", path=None):
    path = (
        Path(path)
        if path
        else Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local/state"))
        / "cosmos/logs/ui.log"
    )
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.close(fd)
    handler = RotatingFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=3)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.basicConfig(level=level, handlers=[handler], force=True)
    logging.getLogger(__name__).info("UI started pid=%s", os.getpid())
    return path
