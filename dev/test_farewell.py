"""Exit summaries must distinguish disconnecting from destroying a session."""

import io
from pathlib import Path
import sys
from types import SimpleNamespace  # noqa: E402
import unittest  # noqa: E402
from unittest.mock import patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from cosmos_tui.ui.farewell import show_farewell  # noqa: E402


class FarewellTests(unittest.TestCase):
    def test_retained_session_has_reconnect_command_without_ansi_in_pipe(self):
        stream = io.StringIO()
        backend = SimpleNamespace(argv=["tmux", "-L", "isolated"], session="study")
        with patch(
            "cosmos_tui.ui.farewell.subprocess.run",
            return_value=SimpleNamespace(returncode=0),
        ) as run:
            show_farewell({"reason": "detach"}, backend, stream)
        self.assertEqual(
            run.call_args.args[0],
            ["tmux", "-L", "isolated", "has-session", "-t", "study"],
        )
        self.assertIn("detach · study", stream.getvalue())
        self.assertIn("Session retained", stream.getvalue())
        self.assertIn("cosmos study", stream.getvalue())
        self.assertNotIn("\x1b", stream.getvalue())

    def test_retained_check_uses_the_stable_session_id(self):
        stream = io.StringIO()
        backend = SimpleNamespace(
            argv=["tmux", "-L", "isolated"], session="study", session_id="$7"
        )
        with patch(
            "cosmos_tui.ui.farewell.subprocess.run",
            return_value=SimpleNamespace(returncode=0),
        ) as run:
            show_farewell({"reason": "detach"}, backend, stream)
        self.assertEqual(
            run.call_args.args[0],
            ["tmux", "-L", "isolated", "has-session", "-t", "$7"],
        )

    def test_ended_session_does_not_promise_reconnect(self):
        stream = io.StringIO()
        backend = SimpleNamespace(argv=["tmux"], session="main")
        with patch(
            "cosmos_tui.ui.farewell.subprocess.run",
            return_value=SimpleNamespace(returncode=1),
        ):
            show_farewell({"reason": "exit"}, backend, stream)
        self.assertIn("exit · main", stream.getvalue())
        self.assertIn("Session ended", stream.getvalue())
        self.assertNotIn("Reconnect:", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
