"""Public command hints and human-facing stop acknowledgement."""

import contextlib
import io
import unittest
from unittest.mock import AsyncMock, patch

from cosmos_tui.core.hints import command, restart_commands, unavailable
from cosmos_tui.core.cli import main


class CommandHintTests(unittest.TestCase):
    def test_public_commands_and_quoting(self):
        self.assertEqual(command("show01"), "cosmos show01")
        self.assertEqual(command("two words"), "cosmos 'two words'")
        self.assertEqual(
            restart_commands("show01", True), "cosmos stop\n  cosmos show01 --debug"
        )
        self.assertEqual(
            unavailable("File backend"),
            "File backend is unavailable; run cosmos doctor for diagnostics",
        )

    def test_stop_acknowledgement_is_not_rpc_json(self):
        output = io.StringIO()
        with (
            patch(
                "cosmos_tui.core.rpc.call", AsyncMock(return_value={"stopping": True})
            ) as rpc,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(main(["stop"]), 0)
        rpc.assert_awaited_once_with("daemon.shutdown", {})
        self.assertEqual(
            output.getvalue(), "Cosmos is stopping · terminal sessions retained\n"
        )
