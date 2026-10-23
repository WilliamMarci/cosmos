"""Calendar UI Mod. Move this folder intact; no host changes are required."""

import calendar
from datetime import date
from cosmos_tui.mods.api import Frame, ModPopup, Static, Text


class CalendarPopup(ModPopup):
    DEFAULT_CSS = """
    CalendarPopup Frame { width: 34; max-width: 100%; height: auto; margin: 0 1 1 0; }
    CalendarPopup Static { height: auto; }
    """

    def __init__(self, api):
        super().__init__()
        self.api = api
        self.year, self.month = date.today().year, date.today().month

    def compose(self):
        with Frame() as frame:
            frame.border_title = "Calendar"
            yield Static(self.content(), markup=False)

    def content(self):
        palette = self.api.palette
        today = date.today()
        text = Text(
            f"{calendar.month_name[self.month]} {self.year}".center(28) + "\n",
            style=palette["fg"],
        )
        text.append("  Mo  Tu  We  Th  Fr  Sa  Su\n", style=palette["mute"])
        for week in calendar.Calendar(firstweekday=0).monthdayscalendar(
            self.year, self.month
        ):
            for day in week:
                style = (
                    f"bold {palette['on']} on {palette['acc']}"
                    if (self.year, self.month, day)
                    == (today.year, today.month, today.day)
                    else palette["fg"]
                )
                text.append(f"{day:>4}" if day else "    ", style=style)
            text.append("\n")
        text.rstrip()
        return text

    def action_month(self, step):
        number = self.year * 12 + self.month - 1 + step
        self.year, self.month = number // 12, number % 12 + 1
        self.query_one(Static).update(self.content())

    def action_today(self):
        self.year, self.month = date.today().year, date.today().month
        self.query_one(Static).update(self.content())


def activate(api):
    api.commands(
        [
            ("previous", "Previous month", ["left", "comma"], "month(-1)"),
            ("next", "Next month", ["right", "full_stop"], "month(1)"),
            ("today", "Current month", ["home"], "today"),
            ("close", "Close calendar", ["escape", "q"], "dismiss"),
            ("help", "Calendar shortcuts", ["question_mark"], "help"),
        ]
    )

    def show():
        api.toggle_popup(CalendarPopup(api))

    api.status_action("clock", show)
