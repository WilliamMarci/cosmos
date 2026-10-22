"""Terminal rendering only. No subprocesses, configuration, or model API calls."""
import time
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window, ConditionalContainer
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.formatted_text import to_formatted_text, fragment_list_to_text
from prompt_toolkit.styles import Style


class InlineUI:
    def __init__(self, backend, initial='', *, command='', command_cursor=None,
                 prompt='$ ', shell_mode=False, native_overlay=False, input=None, output=None):
        self.backend = backend
        self.prompt = prompt.replace('\x01', '').replace('\x02', '')
        self.shell_mode = shell_mode
        self.native_overlay = native_overlay
        self.spinner_started = 0.0
        self.history = []
        self.request_history = []
        self.history_index = None
        self.history_draft = None
        self.busy = False
        self.error = ''
        self.task = None
        self.command = TextArea(text=command, multiline=True, wrap_lines=True,
                                prompt=ANSI(self.prompt), height=self.editor_height)
        self.command.buffer.cursor_position = len(command) if command_cursor is None else command_cursor
        self.input = TextArea(height=1, multiline=False, wrap_lines=False, text=initial, style='class:input')
        keys = KeyBindings()

        @keys.add('enter')
        def enter(event):
            if not self.busy and event.app.layout.has_focus(self.input):
                self.task = event.app.create_background_task(self.generate())
            elif not self.busy and event.app.layout.has_focus(self.command) and self.command.text:
                event.app.exit(result=('run', self.command.text))

        def confirm(event):
            if not self.busy and self.command.text:
                event.app.exit(result=('run', self.command.text))

        @keys.add('c-c')
        @keys.add('c-q')
        @keys.add('escape')
        def cancel(event):
            event.app.exit(result=('cancel', self.command.text))

        @keys.add('c-g')
        def agent(event):
            event.app.exit(result=('agent', self.command.text or self.input.text))

        @keys.add('up', filter=Condition(lambda: self.app.layout.has_focus(self.input)))
        def previous_request(event):
            self.recall_request(-1)

        @keys.add('down', filter=Condition(lambda: self.app.layout.has_focus(self.input)))
        def next_request(event):
            self.recall_request(1)

        @keys.add('tab')
        @keys.add('s-tab')
        def focus(event):
            if self.shell_mode:
                event.app.exit(result=('edit', self.command.text))
            elif self.command.text:
                event.app.layout.focus(self.command if event.app.layout.has_focus(self.input) else self.input)

        def button(label, action, style):
            def click(event):
                if event.event_type == MouseEventType.MOUSE_UP:
                    if action == 'run':
                        confirm(type('Event', (), {'app': self.app})())
                    else:
                        self.app.exit(result=(action, self.command.text or self.input.text))
            return Window(FormattedTextControl([(style, label, click)]),
                          width=len(label), style=style)

        self.status = Window(FormattedTextControl('  '), width=2,
                             style=lambda: 'class:status.' + self.state)
        row = VSplit([
            self.status,
            Window(FormattedTextControl(self.indicator), width=3, style='class:input'),
            self.input,
            ConditionalContainer(Window(FormattedTextControl(lambda: [('class:error', self.error)]),
                width=lambda: min(36, max(8, self.app.output.get_size().columns // 3))),
                Condition(lambda: bool(self.error))),
            button(' ○ ', 'agent', 'class:agent'),
            button(' × ', 'cancel', 'class:cancel'),
            button(' ↵ ', 'run', 'class:run'),
        ], height=1)
        root = HSplit([row] if shell_mode else [self.command, row])
        self.app = Application(layout=Layout(root, focused_element=self.input), key_bindings=keys,
            full_screen=False, erase_when_done=True, mouse_support=True, input=input, output=output,
            refresh_interval=.08,
            style=Style.from_dict({
                'input': 'bg:ansiblack default',
                'error': 'ansired',
                'agent': 'bg:ansiblack ansicyan',
                'cancel': 'bg:ansiblack ansired',
                'run': 'bg:ansiblack ansigreen',
                'status.idle': 'bg:ansibrightblack',
                'status.busy': 'bg:ansiyellow',
                'status.ready': 'bg:ansigreen',
                'status.error': 'bg:ansired',
            }))
        self.app.ttimeoutlen = .05
        self.app.timeoutlen = .05

    def recall_request(self, direction):
        if not self.request_history:
            return
        if self.history_index is None:
            if direction > 0:
                return
            self.history_draft = (self.input.text, self.input.buffer.cursor_position)
            self.history_index = len(self.request_history)
        index = max(0, self.history_index + direction)
        if index >= len(self.request_history):
            text, cursor = self.history_draft
            self.input.text = text
            self.input.buffer.cursor_position = cursor
            self.history_index = self.history_draft = None
        else:
            self.history_index = index
            self.input.text = self.request_history[index]
            self.input.buffer.cursor_position = len(self.input.text)

    def passive_snapshot(self):
        """Two ANSI spans for the shell adapter; it owns positioning and width.

        Generate styles here so the native adapter doesn't duplicate UI colors.
        The long padding is clipped by the adapter without terminal wrapping.
        """
        from io import StringIO
        from prompt_toolkit import print_formatted_text
        from prompt_toolkit.output.vt100 import Vt100_Output
        from prompt_toolkit.data_structures import Size
        def render(fragments):
            stream = StringIO()
            output = Vt100_Output(stream, lambda: Size(rows=1, columns=8192),
                term='xterm-256color', default_color_depth=self.app.output.get_default_color_depth())
            print_formatted_text(FormattedText(fragments), style=self.app.style, output=output, end='')
            return stream.getvalue()
        body = render([('class:status.' + self.state, '  '),
                       ('class:input', ' › ' + self.input.text.replace('\n', ' ') + ' ' * 4096)])
        buttons = render([('class:agent', ' ○ '), ('class:cancel', ' × '), ('class:run', ' ↵ ')])
        return body, buttons

    def indicator(self):
        if self.busy:
            frames = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
            return ' ' + frames[int((time.monotonic() - self.spinner_started) / .08) % len(frames)] + ' '
        return ' ! ' if self.error else ' › '

    def editor_height(self):
        columns = self.app.output.get_size().columns if hasattr(self, 'app') else 80
        return display_rows(self.prompt, self.command.text, columns)

    @property
    def state(self):
        if self.busy:
            return 'busy'
        if self.error:
            return 'error'
        return 'ready' if self.command.text else 'idle'

    async def generate(self):
        text = self.input.text.strip()
        if not text:
            return
        self.request_history.append(text)
        self.history_index = self.history_draft = None
        self.busy, self.error = True, ''
        self.spinner_started = time.monotonic()
        self.app.invalidate()
        request = self.history + [{'request': text, 'previous_command': self.command.text}]
        try:
            command = await self.backend.propose(request)
            self.history = request
            self.command.text = command
            self.command.buffer.cursor_position = len(command)
            self.input.text = ''
            if self.shell_mode:
                self.app.exit(result=('update', command))
        except Exception as exc:
            self.error = str(exc).replace('\n', ' ')[:180]
            # Keep errors inside the one-row popup, rather than adding a row.
            # Keep the original request available for retry.
            self.app.invalidate()
        finally:
            self.busy = False
            self.app.invalidate()

    def run(self):
        output = self.app.output
        def prepare():
            if self.shell_mode and not self.native_overlay:
                from prompt_toolkit import print_formatted_text
                # bind -x cleared the visible Readline line. Restore its text as
                # a noninteractive display, then draw only our one-row popup.
                # Native command editing resumes in Bash after the Tab result.
                output.write_raw('\r\x1b[J')
                print_formatted_text(ANSI(self.prompt), self.command.text,
                                     sep='', output=output)
                output.flush()
        try:
            prepare()
            return self.app.run()
        finally:
            if self.shell_mode and not self.native_overlay:
                rows = painted_rows(self.prompt, self.command.text, output.get_size().columns)
                output.write_raw('\r' + f'\x1b[{rows}A' + '\x1b[J')
                output.flush()


def display_rows(prompt, text, columns):
    """Physical rows through a readline cursor, including ANSI prompts and wraps."""
    plain = fragment_list_to_text(to_formatted_text(ANSI(prompt.replace('\x01', '').replace('\x02', ''))))
    columns = max(1, columns)
    rows, column = 1, 0
    for char in plain + text:
        if char == '\n':
            rows, column = rows + 1, 0
        elif char == '\r':
            column = 0
        else:
            width = (8 - column % 8) if char == '\t' else max(0, get_cwidth(char))
            if column + width > columns:
                rows, column = rows + 1, 0
            column += width
            if column >= columns:
                rows, column = rows + column // columns, column % columns
    return rows


def painted_rows(prompt, text, columns):
    """Rows painted before a final newline, including pending terminal wraps."""
    plain = fragment_list_to_text(to_formatted_text(ANSI(prompt)))
    rows, column = 1, 0
    for char in plain + text:
        if char == '\n':
            rows, column = rows + 1, 0
        elif char == '\r':
            column = 0
        else:
            width = (8 - column % 8) if char == '\t' else max(0, get_cwidth(char))
            if width and column + width > max(1, columns):
                rows, column = rows + 1, 0
            column += width
    return rows
