"""One Leader map shared by the workspace and every modal context."""

from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input

LEADER_KEYS = (
    "p",
    "a",
    "g",
    "s",
    "question_mark",
    "full_stop",
    "N",
    "d",
    "c",
    "percent_sign",
    "quotation_mark",
    "vertical_line",
    "minus",
    "H",
    "J",
    "K",
    "L",
    "n",
    "b",
    "o",
    "z",
    "up",
    "down",
    "left",
    "right",
    *map(str, range(10)),
)


def leader_bindings(modal=False):
    namespace = "app." if modal else ""
    return [
        Binding("ctrl+b", f"{namespace}leader('ctrl+b')", show=False, priority=True),
        Binding("ctrl+a", f"{namespace}leader('ctrl+a')", show=False, priority=True),
    ] + [
        Binding(key, f"{namespace}leader_key('{key}')", show=False, priority=True)
        for key in LEADER_KEYS
    ]


class CosmosModal(ModalScreen):
    BINDINGS = leader_bindings(modal=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.styles.background = "transparent"
        self.styles.background_tint = "transparent"

    async def on_mount(self):
        if hasattr(self.app, "notification_events"):
            from cosmos_tui.features.notifications.toast import NoticeToast

            await self.mount(NoticeToast(id="cosmos-modal-notice"))

    def on_click(self, event):
        if not hasattr(self.app, "action_start_menu"):
            return
        status = self.app.query_one("#status")
        if status.display and status.region.contains(event.screen_x, event.screen_y):
            if hasattr(status, "activate_at"):
                if status.activate_at(event.screen_x - status.region.x):
                    event.stop()
            elif event.screen_x < status.region.x + 8:
                event.stop()
                self.app.action_start_menu()


class CosmosInput(Input):
    """Keep normal typing local, but release the next Leader key to global actions."""

    def check_consume_key(self, key, character):
        if self.app.prefix:
            return False
        return super().check_consume_key(key, character)

    def on_key(self, event):
        if self.app.prefix:
            self.app.prefix = False
            event.stop()
            event.prevent_default()


# Kitty reports modifier presses as keys in addition to the resulting character.
# They must neither consume a pending Leader nor be forwarded to a child PTY.
MODIFIER_KEYS = frozenset(
    f"{side}_{name}"
    for side in ("left", "right")
    for name in ("shift", "control", "alt", "super", "hyper", "meta")
) | {"iso_level3_shift", "iso_level5_shift", "caps_lock", "num_lock"}


def leader_key(key, character):
    aliases = {
        "%": "percent_sign",
        '"': "quotation_mark",
        "|": "vertical_line",
        "-": "minus",
        "?": "question_mark",
        ".": "full_stop",
        ",": "comma",
        " ": "space",
        "$": "dollar_sign",
        "+": "plus",
        "=": "equals_sign",
        "/": "slash",
        "[": "left_square_bracket",
        "]": "right_square_bracket",
    }
    if key.startswith(("ctrl+", "alt+", "meta+")):
        return key
    if character and character.isprintable():
        return aliases.get(character, character)
    # Protocols without associated text still provide Shift plus the base key.
    shifted = {
        "apostrophe": "quotation_mark",
        "5": "percent_sign",
        "backslash": "vertical_line",
        "slash": "question_mark",
    }
    if key.startswith("shift+"):
        base = key[6:]
        return shifted.get(base, base.upper() if len(base) == 1 else base)
    return key
