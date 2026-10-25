"""Switch tree controls, new-session cwd and stable-target pane selection."""

import tempfile
import shlex
import unittest
from unittest.mock import patch
from textual.widgets import ListView, Input
from test_navigation import Probe as BaseProbe
from cosmos_tui.features.navigation.switcher import Switcher
from cosmos_tui.features.navigation.switch_rows import SwitchRow
from cosmos_tui.features.navigation.session_prompt import NewSession
from cosmos_tui.input.shortcuts import CosmosInput
from cosmos_tui.terminal.tmux import Pane, Tmux


class Backend:
    tabs = [["@3", "0", "1", "shell"]]
    session = "main"
    session_id = "$7"
    quote = staticmethod(shlex.quote)
    validate_name = staticmethod(Tmux.validate_name)

    def __init__(self, cwd):
        self.cwd = cwd
        self.selected = None
        self.calls = []
        self.windows = [
            dict(
                session_id="$7",
                session="main",
                window_id="@3",
                index="0",
                name="shell",
                active=True,
            ),
            dict(
                session_id="$7",
                session="main",
                window_id="@4",
                index="1",
                name="editor",
                active=False,
            ),
        ]
        self.title = ""

    async def inventory(self):
        return self.windows.copy()

    async def request(self, command):
        self.calls.append(command)
        if command.startswith("list-panes -a"):
            return [f"$7|@3|%8|0|bash|{self.title}", "$7|@3|%9|1|python|"]
        if "pane_current_path" in command:
            return [self.cwd]
        if "display-message" in command and "window_id" in command:
            return ["@3"]
        if command.startswith("set-option -p -t %8 @cosmos_name "):
            self.title = shlex.split(command)[-1]
        return []

    async def snapshot(self, window=None):
        return [
            Pane(
                "%8",
                0,
                0,
                40,
                23,
                True,
                [],
                "",
                (0, 0),
                index=0,
                window_id="@3",
                session_id="$7",
            ),
            Pane(
                "%9",
                41,
                0,
                39,
                23,
                False,
                [],
                "",
                (0, 0),
                index=1,
                window_id="@3",
                session_id="$7",
            ),
        ]

    async def select_window(self, row):
        self.selected = row


class SwitchTreeTests(unittest.IsolatedAsyncioTestCase):
    async def test_tree_controls_rename_and_pane_selection(self):
        with tempfile.TemporaryDirectory() as root:
            app = BaseProbe()
            async with app.run_test(size=(120, 40)) as pilot:
                app.backend = Backend(root)
                await pilot.press("ctrl+b", "s")
                await pilot.pause()
                screen = app.screen
                await screen.inventory_ready.wait()
                await pilot.pause()
                self.assertIsInstance(screen, Switcher)
                self.assertEqual([r["kind"] for r in screen.rows], ["session"])
                await pilot.press("right")
                screen.query_one(ListView).index = 1
                await pilot.press("right")
                self.assertEqual(
                    [r["kind"] for r in screen.rows],
                    ["session", "window", "pane", "pane", "window"],
                )
                screen.query_one(ListView).index = 2
                await pilot.pause()
                widget = screen.query(SwitchRow)[2]
                painted = widget.render()
                row_bg = painted.get_style_at_offset(app.console, 4).bgcolor
                self.assertNotEqual(row_bg.name, app.role_colors["acc"])
                self.assertEqual(
                    row_bg,
                    painted.get_style_at_offset(
                        app.console, widget.hits[-1][0]
                    ).bgcolor,
                )
                self.assertEqual(
                    [name for _, _, name in widget.hits], ["rename", "more"]
                )
                await pilot.press("ctrl+r")
                await pilot.pause()
                app.screen.query_one(CosmosInput).value = "worker"
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.backend.title, "worker")
                selected_widget = screen.query(SwitchRow)[2]
                selected_widget.render()
                await pilot.click(
                    selected_widget, offset=(selected_widget.hits[-1][0] + 1, 0)
                )
                await pilot.pause()
                from cosmos_tui.ui.menus import CompactMenu

                self.assertIsInstance(app.screen, CompactMenu)
                await pilot.press("escape")
                self.assertTrue(
                    any(r.get("pane_name") == "worker" for r in screen.rows)
                )
                screen.query_one(Input).value = "%9"
                await pilot.pause(0.3)
                self.assertEqual(screen.rows[-1]["pane_id"], "%9")
                screen.query_one(ListView).index = len(screen.rows) - 1
                await pilot.press("enter")
                await pilot.pause()
                self.assertIn("select-pane -t %9", app.backend.calls)
                self.assertIs(app.screen, app._workspace_screen)
                await pilot.press("ctrl+b", "s")
                await app.screen.inventory_ready.wait()
                self.assertIn("$7:@3", app.screen.expanded)
                app.screen.query_one(ListView).index = 0
                await pilot.press("left", "escape", "ctrl+b", "s")
                await app.screen.inventory_ready.wait()
                self.assertEqual([r["kind"] for r in app.screen.rows], ["session"])

    async def test_identify_panes_selects_stable_id_without_typing_digit(self):
        app = BaseProbe()
        async with app.run_test(size=(100, 32)) as pilot:
            app.panes = [
                Pane("%8", 0, 0, 49, 29, True, [], "", (0, 0), index=0),
                Pane("%19", 50, 0, 50, 29, False, [], "", (0, 0), index=1),
            ]
            await pilot.press("ctrl+b", "q")
            self.assertTrue(app.workspace.identifying)
            text = app.query_one("#terminal").render_line(14).text
            self.assertIn("%8", text)
            self.assertIn("%19", text)
            app.backend.request.reset_mock()
            await pilot.press("1")
            self.assertFalse(app.workspace.identifying)
            app.backend.request.assert_awaited_once_with("select-pane -t %19")

    async def test_new_session_button_inherits_cwd(self):
        with tempfile.TemporaryDirectory() as root:
            app = BaseProbe()
            async with app.run_test(size=(110, 36)) as pilot:
                app.backend = Backend(root)

                async def create(name, cwd=None):
                    self.assertEqual((name, cwd), ("research", root))
                    app.backend.windows.append(
                        dict(
                            session_id="$10",
                            session=name,
                            window_id="@20",
                            index="0",
                            name="bash",
                            active=True,
                        )
                    )
                    return "$10"

                with patch(
                    "cosmos_tui.features.navigation.session_prompt.create",
                    side_effect=create,
                ) as factory:
                    await pilot.press("ctrl+b", "s")
                    await pilot.pause()
                    await app.screen.inventory_ready.wait()
                    await pilot.click("#switch-new")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, NewSession)
                    app.screen.query_one(CosmosInput).value = "research"
                    await pilot.press("enter")
                    await pilot.pause()
                    factory.assert_awaited_once()
                    self.assertEqual(app.backend.selected["session_id"], "$10")
                    self.assertIs(app.screen, app._workspace_screen)
