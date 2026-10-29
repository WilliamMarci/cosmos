"""Files: real temporary mutations, Cosmos routing, columns and status metadata."""

import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from test_navigation import Probe, snapshot
from textual.widgets import ListView
from cosmos_tui.features.files import operations
from cosmos_tui.features.files.model import entries
from cosmos_tui.features.files.style import appearance, metadata
from cosmos_tui.features.settings.panel import Palette
from cosmos_tui.input.shortcuts import CosmosInput
from cosmos_tui.features.status.bar import StatusBar
from cosmos_tui.input import keymap


class FileOperationsTests(unittest.TestCase):
    def test_copy_move_conflicts_links_and_trash(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source, destination = root / "source", root / "destination"
            source.mkdir()
            destination.mkdir()
            (source / "data").write_text("original")
            (source / "link").symlink_to("data")
            (source / "dangling").symlink_to("missing")
            operations.transfer(
                [source / "data", source / "link", source / "dangling"], destination
            )
            self.assertEqual((destination / "data").read_text(), "original")
            self.assertEqual(os.readlink(destination / "link"), "data")
            self.assertTrue((destination / "dangling").is_symlink())
            with self.assertRaises(FileExistsError):
                operations.transfer([source / "data"], destination)
            self.assertEqual((destination / "data").read_text(), "original")
            operations.rename(source / "data", "renamed")
            operations.transfer([source / "renamed"], destination, True)
            self.assertFalse((source / "renamed").exists())
            self.assertEqual((destination / "renamed").read_text(), "original")
            operations.create(source, "folder", True)
            operations.create(source / "folder", "inside")
            with self.assertRaises(ValueError):
                operations.transfer([source / "folder"], source / "folder")
            with self.assertRaises(ValueError):
                operations.create(source, "../outside")
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(root / "data-home")}):
                operations.trash([destination / "link", source / "folder"])
            self.assertFalse((destination / "link").is_symlink())
            self.assertTrue((destination / "data").exists())
            self.assertEqual(
                len(list((root / "data-home/Trash/info").glob("*.trashinfo"))), 2
            )
            self.assertEqual(len(list((root / "data-home/Trash/files").iterdir())), 2)


class FilesUITests(unittest.IsolatedAsyncioTestCase):
    async def test_render_keys_settings_and_status(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "workspace with spaces"
            directory.mkdir()
            (directory / "folder").mkdir()
            (directory / "file2.py").write_text("print(2)")
            (directory / "file10.pdf").write_bytes(b"pdf")
            (directory / "link").symlink_to("file2.py")
            app = Probe()
            state = snapshot()
            state["settings"].update(files_icons=False, files_border="dividers")

            async def rpc(method, params=None):
                if method == "state.snapshot":
                    return copy.deepcopy(state)
                if method == "settings.get":
                    return copy.deepcopy(state["settings"])
                if method == "settings.replace":
                    state["settings"] = copy.deepcopy(params)
                    return {}
                return []

            with (
                patch("cosmos_tui.core.rpc.call", side_effect=rpc),
                patch("cosmos_tui.features.agent.launch.runtime"),
                patch.dict(
                    os.environ, {"XDG_DATA_HOME": str(Path(root) / "data-home")}
                ),
            ):
                async with app.run_test(size=(120, 38)) as pilot:
                    pane = app.panes[0]
                    pane.width = 120
                    pane.height = 36
                    view = dict(kind="files", path=str(directory), cursor=1)
                    pane.viewer = base64.b64encode(json.dumps(view).encode()).decode()
                    manager = app.reader_ui.files
                    self.assertEqual(app.key_context(), "files")
                    frame = manager.render(pane, view, app.role_colors, (8, 16))
                    self.assertIn(
                        "file2.py", "\n".join(line.plain for line in frame.lines)
                    )
                    self.assertEqual(frame.main_x, 21)
                    items = entries(view)
                    link = next(i for i in items if i["link"])
                    folder = next(i for i in items if i["directory"])
                    self.assertNotEqual(
                        appearance(link, app.role_colors)[0],
                        appearance(folder, app.role_colors)[0],
                    )
                    info = metadata(items, 1)
                    bar = app.query_one("#status", StatusBar)
                    bar.present(
                        label="FILES",
                        index=0,
                        name="bash",
                        path="",
                        branch="",
                        file_info=info,
                        mode="files",
                    )
                    self.assertIn(info["permissions"], bar._content.plain)
                    self.assertIn("2/4", bar._content.plain)
                    self.assertNotIn(str(directory), bar._content.plain)
                    app.session_windows.open = AsyncMock()
                    await pilot.press("t", "g")
                    self.assertEqual(
                        app.session_windows.open.await_args_list[0].kwargs["cwd"],
                        str(directory),
                    )
                    command = app.session_windows.open.await_args_list[1].args[0]
                    self.assertEqual(
                        command[1:4], ["-m", "cosmos_tui.features.agent", "launch"]
                    )
                    self.assertIn(pane.id, command)
                    await pilot.press("space", "y")
                    self.assertEqual(
                        manager.clipboard[0], (str(directory / "file2.py"),)
                    )
                    self.assertEqual(
                        app.reader_ui.state(pane)["selected"],
                        [str(directory / "file2.py")],
                    )
                    app.push_screen(Palette("files_settings"))
                    await pilot.pause()
                    menu = app.screen
                    menu.query_one(ListView).index = 0
                    await pilot.press("right")
                    self.assertTrue(state["settings"]["files_icons"])
                    menu.query_one(ListView).index = 1
                    await pilot.press("right")
                    self.assertEqual(state["settings"]["files_border"], "frame")
                    menu.dismiss(None)
                    await pilot.pause()
                    frame = manager.render(pane, view, app.role_colors, (8, 16))
                    self.assertTrue(frame.lines[0].plain.startswith("╭"))
                    self.assertIn("┴", frame.lines[-1].plain)
                    self.assertTrue(any("󰉋" in line.plain for line in frame.lines))
                    ids = {c.id for c in keymap.COMMANDS if c.context == "files"}
                    self.assertTrue(
                        {
                            "files.copy",
                            "files.cut",
                            "files.paste",
                            "files.trash",
                            "files.agent",
                            "files.terminal",
                        }
                        <= ids
                    )

                    # Exercise mutation routing, not only the pure filesystem functions.
                    await pilot.press("home", "enter", "p")
                    await app.workers.wait_for_complete()
                    self.assertEqual(
                        (directory / "folder/file2.py").read_text(), "print(2)"
                    )
                    await pilot.press("r")
                    app.screen.query_one(CosmosInput).value = "renamed.py"
                    await pilot.press("enter")
                    await app.workers.wait_for_complete()
                    self.assertTrue((directory / "folder/renamed.py").exists())
                    await pilot.press("d")
                    await pilot.press("down", "enter")
                    await app.workers.wait_for_complete()
                    self.assertFalse((directory / "folder/renamed.py").exists())
                    self.assertEqual(
                        len(
                            list(
                                (Path(root) / "data-home/Trash/info").glob(
                                    "*.trashinfo"
                                )
                            )
                        ),
                        1,
                    )
                    await pilot.press("q")
