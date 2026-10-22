import asyncio
import unittest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from terminal_agent.ui import InlineUI


class Backend:
    async def propose(self, history):
        return 'printf hello'


class UITests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_edit_confirm(self):
        with create_pipe_input() as pipe:
            ui = InlineUI(Backend(), initial='生成命令', input=pipe, output=DummyOutput())
            task = asyncio.create_task(ui.app.run_async())
            pipe.send_text('\r')
            for _ in range(100):
                if ui.command.text:
                    break
                await asyncio.sleep(.01)
            self.assertEqual(ui.command.text, 'printf hello')
            pipe.send_text('\t\x05!')
            await asyncio.sleep(.05)
            self.assertFalse(task.done(), 'editing alone must not execute')
            pipe.send_text('\r')
            self.assertEqual(await asyncio.wait_for(task, 2), ('run', 'printf hello!'))

    async def test_cancel(self):
        with create_pipe_input() as pipe:
            ui = InlineUI(Backend(), input=pipe, output=DummyOutput())
            task = asyncio.create_task(ui.app.run_async())
            pipe.send_text('\x1b')
            self.assertEqual(await asyncio.wait_for(task, 2), ('cancel', ''))

    async def test_native_popup_yields_to_readline_on_tab(self):
        with create_pipe_input() as pipe:
            ui = InlineUI(Backend(), command='printf original', initial='more details',
                          shell_mode=True, input=pipe, output=DummyOutput())
            self.assertEqual(len(ui.app.layout.container.children), 1)
            self.assertFalse(any(str(key) in ('Keys.ControlR', 'c-r')
                for binding in ui.app.key_bindings.bindings for key in binding.keys))
            task = asyncio.create_task(ui.app.run_async())
            pipe.send_text('\t')
            self.assertEqual(await asyncio.wait_for(task, 2), ('edit', 'printf original'))
            self.assertEqual(ui.input.text, 'more details')

    async def test_generation_returns_update_to_native_shell(self):
        with create_pipe_input() as pipe:
            ui = InlineUI(Backend(), initial='generate', shell_mode=True,
                          input=pipe, output=DummyOutput())
            task = asyncio.create_task(ui.app.run_async())
            pipe.send_text('\r')
            self.assertEqual(await asyncio.wait_for(task, 2), ('update', 'printf hello'))

    async def test_escape_keeps_latest_editor_and_cursor(self):
        with create_pipe_input() as pipe:
            ui = InlineUI(Backend(), command='printf original', command_cursor=3,
                          input=pipe, output=DummyOutput())
            task = asyncio.create_task(ui.app.run_async())
            pipe.send_text('\x1b')
            self.assertEqual(await asyncio.wait_for(task, 2), ('cancel', 'printf original'))
            self.assertEqual(ui.command.buffer.cursor_position, 3)

    def test_main_editor_is_always_present_and_theme_uses_ansi(self):
        with create_pipe_input() as pipe:
            ui = InlineUI(Backend(), input=pipe, output=DummyOutput())
            self.assertEqual(len(ui.app.layout.container.children), 2)
            self.assertTrue(ui.app.erase_when_done)
            self.assertTrue(all('#' not in value for _, value in ui.app.style.style_rules))

    def test_prompt_and_wrapping(self):
        from terminal_agent.ui import display_rows
        self.assertEqual(display_rows('\x01\x1b[32m\x02$ \x1b[0m', '123', 80), 1)
        self.assertEqual(display_rows('long\nprompt> ', '中' * 5, 10), 3)


    def test_braille_spinner_has_stable_width(self):
        from unittest.mock import patch
        with create_pipe_input() as pipe:
            ui = InlineUI(Backend(), shell_mode=True, native_overlay=True,
                          input=pipe, output=DummyOutput())
            ui.busy, ui.spinner_started = True, 0
            with patch('terminal_agent.ui.time.monotonic', return_value=.01):
                first = ui.indicator()
            with patch('terminal_agent.ui.time.monotonic', return_value=.11):
                second = ui.indicator()
            self.assertNotEqual(first, second)
            self.assertEqual(len(first), 3)
            self.assertIn(first.strip(), '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏')


    async def test_request_history_restores_draft_and_cursor(self):
        with create_pipe_input() as pipe:
            ui = InlineUI(Backend(), initial='未完成的草稿', input=pipe, output=DummyOutput())
            ui.request_history = ['第一个要求', '第二个要求']
            ui.input.buffer.cursor_position = 3
            task = asyncio.create_task(ui.app.run_async())
            for key, expected in [('\x1b[A', '第二个要求'), ('\x1b[A', '第一个要求'),
                                  ('\x1b[A', '第一个要求'), ('\x1b[B', '第二个要求'),
                                  ('\x1b[B', '未完成的草稿')]:
                pipe.send_text(key)
                await asyncio.sleep(.03)
                self.assertEqual(ui.input.text, expected)
            self.assertEqual(ui.input.buffer.cursor_position, 3)
            pipe.send_text('\x1b')
            await asyncio.wait_for(task, 2)

    def test_passive_snapshot_uses_same_single_line_ui(self):
        with create_pipe_input() as pipe:
            ui = InlineUI(Backend(), initial='draft 中文', input=pipe, output=DummyOutput())
            body, buttons = ui.passive_snapshot()
            self.assertIn('draft 中文', body)
            self.assertNotIn('class:', body)
            self.assertIn('○', buttons)
            self.assertIn('×', buttons)
            self.assertIn('↵', buttons)
            self.assertNotIn('\n', body)
