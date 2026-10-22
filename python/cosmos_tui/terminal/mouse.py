"""Client-local SGR mouse policy, independent of image graphics.

The input pump follows Textual 8.2.8 LinuxDriver (MIT); keeping the parser
instance here lets Cell override Textual's automatic pixel-coordinate switch.
Upstream copyright and MIT notice: packaging/notices/textual-MIT.txt.
"""

import os
import re
import selectors
import struct
import fcntl
import termios
from codecs import getincrementaldecoder

from textual import events
from textual._parser import ParseError
from textual._xterm_parser import XTermParser
from textual.drivers.linux_driver import LinuxDriver

MODES = ("auto", "cell", "pixel")


class MouseParser(XTermParser):
    def __init__(self, driver):
        self.driver = driver
        self.reports = ""
        super().__init__(driver._debug)

    def feed(self, data):
        self.reports = (self.reports + data)[-256:]
        reports = list(re.finditer(r"\x1b\[\?1016;([0-4])\$y", self.reports))
        if reports:
            self.driver.pixel_supported = int(reports[-1][1]) in (1, 2, 3)
            self.reports = ""
            self.driver.apply_mouse_mode()
        yield from super().feed(data)

    def parse_mouse_code(self, code):
        self.mouse_pixels = self.driver.effective_mouse_mode == "pixel"
        return super().parse_mouse_code(code)


class CosmosLinuxDriver(LinuxDriver):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mouse_parser = None
        self.pixel_supported = False
        self.effective_mouse_mode = "cell"

    def apply_mouse_mode(self):
        parser = self.mouse_parser
        geometry = bool(
            parser
            and parser.terminal_size
            and parser.terminal_pixel_size
            and all(parser.terminal_size)
            and all(parser.terminal_pixel_size)
        )
        requested = self._app.mouse_mode
        effective = (
            "pixel"
            if geometry
            and (requested == "pixel" or requested == "auto" and self.pixel_supported)
            else "cell"
        )
        if self._mouse:
            self.write(
                "\x1b[?1016h" if effective == "pixel" else "\x1b[?1016l\x1b[?1006h"
            )
            self.flush()
        self._mouse_pixels = effective == "pixel"
        self.effective_mouse_mode = effective
        if parser:
            parser.mouse_pixels = self._mouse_pixels

    def _enable_mouse_support(self):
        super()._enable_mouse_support()
        if self._mouse:
            self.write("\x1b[?1016$p")
            self.apply_mouse_mode()

    def _enable_mouse_pixels(self):
        self.apply_mouse_mode()

    def _disable_mouse_support(self):
        if self._mouse:
            self.write("\x1b[?1016l")
        super()._disable_mouse_support()

    def process_message(self, message):
        if isinstance(message, events.Resize):
            self.apply_mouse_mode()
        super().process_message(message)

    def run_input_thread(self):
        selector = selectors.SelectSelector()
        selector.register(self.fileno, selectors.EVENT_READ)
        parser = self.mouse_parser = MouseParser(self)
        try:
            rows, cols, width, height = struct.unpack(
                "HHHH", fcntl.ioctl(self.fileno, termios.TIOCGWINSZ, b"\0" * 8)
            )
            if rows and cols and width and height:
                parser.terminal_size = cols, rows
                parser.terminal_pixel_size = width, height
        except OSError:
            pass
        self.apply_mouse_mode()
        decode = getincrementaldecoder("utf-8")().decode

        def process(ready, final=False):
            for index, (_, mask) in enumerate(ready):
                if mask & selectors.EVENT_READ:
                    data = decode(
                        os.read(self.fileno, 4096),
                        final=final and index == len(ready) - 1,
                    )
                    if not data:
                        break
                    for event in parser.feed(data):
                        self.process_message(event)
            for event in parser.tick():
                self.process_message(event)

        try:
            while not self.exit_event.is_set():
                process(selector.select(0.1))
            selector.unregister(self.fileno)
            process(selector.select(0.1), final=True)
        finally:
            selector.close()
            try:
                list(parser.feed(""))
            except (EOFError, ParseError):
                pass
