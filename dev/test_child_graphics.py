"""Pane apps that emit Kitty graphics are bridged to the outer terminal."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rich.style import Style
from rich.text import Text

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "python")]

from cosmos_tui.render.ansi import decode_grid  # noqa: E402
from cosmos_tui.render.graphics import Graphics  # noqa: E402
from cosmos_tui.terminal.child_graphics import (  # noqa: E402
    KittyStream,
    unescape_output,
)
from cosmos_tui.terminal.tmux import Tmux  # noqa: E402


class ChildGraphicsParserTests(unittest.TestCase):
    def test_control_mode_octal_unescape(self):
        self.assertEqual(
            unescape_output(b"\\033_Gi=1\\033\\134"), b"\x1b_Gi=1\x1b\\"
        )
        self.assertEqual(unescape_output(b"plain\\015\\012"), b"plain\r\n")

    def test_direct_and_tmux_wrapped_sequences(self):
        stream = KittyStream()
        direct = b"\x1b_Gi=1,a=t;AAAA\x1b\\"
        inner = b"\x1b_Gi=2,a=t;BBBB\x1b\\"
        wrapped = b"\x1bPtmux;" + inner.replace(b"\x1b", b"\x1b\x1b") + b"\x1b\\"
        self.assertEqual(stream.feed(direct + b"ignored" + wrapped), [direct, inner])

    def test_split_sequences_survive_arbitrary_chunks(self):
        stream = KittyStream()
        sequence = b"\x1bPtmux;" + b"\x1b_Gi=7,a=t;AAAA\x1b\\".replace(
            b"\x1b", b"\x1b\x1b"
        ) + b"\x1b\\"
        self.assertEqual(stream.feed(sequence[:7]), [])
        self.assertEqual(stream.feed(sequence[7:12]), [])
        self.assertEqual(
            stream.feed(sequence[12:]), [b"\x1b_Gi=7,a=t;AAAA\x1b\\"]
        )


class ChildGraphicsBridgeTests(unittest.TestCase):
    def graphics(self, *, tmux=False):
        env = {
            "COSMOS_GRAPHICS": "kitty",
            "TERM": "xterm-ghostty",
        }
        if tmux:
            env["TMUX"] = "/tmp/tmux,1,0"
        with patch.dict(os.environ, env, clear=False):
            if not tmux:
                os.environ.pop("TMUX", None)
            return Graphics()

    def test_transmit_placement_and_delete_share_a_namespaced_id(self):
        graphics = self.graphics()
        graphics.feed_child("%0", b"\x1b_Gq=2,a=t,U=1,i=42,m=0;AAAA\x1b\\")
        graphics.feed_child("%0", b"\x1b_Gq=2,a=p,U=1,i=42,c=2,r=1\x1b\\")
        new_id = graphics.child_maps["%0"][42]
        self.assertNotEqual(new_id, 42)
        self.assertEqual(graphics.child_colors["%0"], {"#00002a": f"#{new_id:06x}"})
        self.assertIn(f"i={new_id}", graphics.pending)
        self.assertNotIn("i=42", graphics.pending)
        graphics.feed_child("%0", b"\x1b_Gq=2,a=d,d=I,i=42\x1b\\")
        self.assertIn(f"d=I,i={new_id}", graphics.pending)
        self.assertNotIn(42, graphics.child_maps.get("%0", {}))

    def test_chunk_continuation_keeps_the_original_image(self):
        graphics = self.graphics()
        graphics.feed_child("%0", b"\x1b_Gq=2,a=t,U=1,i=9,m=1;AAAA\x1b\\")
        graphics.feed_child("%0", b"\x1b_Gm=0;BBBB\x1b\\")
        new_id = graphics.child_maps["%0"][9]
        self.assertEqual(graphics.pending.count(f"i={new_id}"), 1)
        self.assertIn("m=0;BBBB", graphics.pending)

    def test_recolor_replaces_only_placeholder_foregrounds(self):
        graphics = self.graphics()
        graphics.feed_child("%0", b"\x1b_Gq=2,a=t,U=1,i=42;AAAA\x1b\\")
        new_id = graphics.child_maps["%0"][42]
        placeholder = Text()
        placeholder.append(
            "\U0010eeee\u0305\u0305", style=Style(color="#00002a")
        )
        other = Text()
        other.append("ordinary", style=Style(color="#00002a"))
        colored = graphics.recolor("%0", [placeholder, other])
        self.assertEqual(
            colored[0].spans[0].style.color.get_truecolor(),
            Style(color=f"#{new_id:06x}").color.get_truecolor(),
        )
        self.assertEqual(placeholder.spans[0].style.color.get_truecolor(), (0, 0, 42))
        self.assertEqual(colored[1].spans[0].style.color.get_truecolor(), (0, 0, 42))

    def test_delete_all_targets_only_child_images(self):
        graphics = self.graphics()
        graphics.feed_child("%0", b"\x1b_Gq=2,a=t,U=1,i=42;AAAA\x1b\\")
        new_id = graphics.child_maps["%0"][42]
        graphics.pending = ""
        graphics.feed_child("%0", b"\x1b_Gq=2,a=d,d=A\x1b\\")
        self.assertIn(f"d=I,i={new_id}", graphics.pending)
        self.assertNotIn("d=A", graphics.pending)
        self.assertEqual(graphics.child_maps, {})

    def test_outer_tmux_wraps_graphics_apcs(self):
        graphics = self.graphics(tmux=True)
        graphics.feed_child("%0", b"\x1b_Gq=2,a=t,U=1,i=42;AAAA\x1b\\")
        self.assertTrue(graphics.pending.startswith("\x1bPtmux;"))
        self.assertTrue(graphics.pending.endswith("\x1b\\"))


@unittest.skipUnless(
    os.getenv("COSMOS_TEST_TMUX"), "set COSMOS_TEST_TMUX=1 for isolated Tmux tests"
)
class ChildGraphicsControlModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_control_mode_output_reaches_the_bridge_with_placeholders(self):
        with tempfile.TemporaryDirectory(prefix="cosmos-child-gfx-") as temp:
            socket = Path(temp).name
            env = dict(
                os.environ,
                HOME=temp,
                COSMOS_TMUX_SOCKET=socket,
                TERM="xterm-ghostty",
                COSMOS_GRAPHICS="kitty",
            )
            script = Path(temp) / "emit.py"
            script.write_text(
                "import base64, os, time, zlib\n"
                "data = base64.b64encode(zlib.compress(b'\\xff\\x00\\x00\\xff')).decode()\n"
                "os.write(1, f'\\x1b_Gq=2,a=t,U=1,f=32,o=z,s=1,v=1,i=42;{data}\\x1b\\\\'.encode())\n"
                "os.write(1, b'\\x1b_Gq=2,a=p,U=1,i=42,c=1,r=1\\x1b\\\\')\n"
                "os.write(1, ('\\x1b[38;2;0;0;42m\\U0010eeee\\u0305\\u0305\\x1b[0m').encode())\n"
                "time.sleep(2)\n"
            )
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("TMUX", None)
                backend = Tmux("gfx")
                try:
                    await backend.connect()
                    await backend.cli(
                        "send-keys", "-t", "gfx", f"python3 {script}", "Enter"
                    )
                    for _ in range(40):
                        await asyncio.sleep(0.05)
                        if backend.child_graphics:
                            break
                    events = backend.take_child_graphics()
                    graphics = Graphics()
                    for pane, sequence in events:
                        graphics.feed_child(pane, sequence)
                    self.assertTrue(graphics.child_maps)
                    panes = await backend.snapshot()
                    self.assertTrue(
                        any(
                            "\U0010eeee" in "".join(pane.lines)
                            for pane in panes
                        )
                    )
                    colored = graphics.recolor(
                        panes[0].id, list(decode_grid(tuple(panes[0].lines)))
                    )
                    self.assertTrue(any("\U0010eeee" in line.plain for line in colored))
                finally:
                    await backend.close()
                    subprocess.run(
                        [os.getenv("COSMOS_TMUX", "tmux"), "-L", socket, "kill-server"],
                        env=env,
                        capture_output=True,
                    )


if __name__ == "__main__":
    unittest.main()
