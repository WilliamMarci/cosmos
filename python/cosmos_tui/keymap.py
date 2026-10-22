"""Single command registry for settings, dispatch and contextual help."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    id: str
    context: str
    label: str
    keys: tuple[str, ...]
    target: str


COMMANDS = []


def register(id, context, label, keys, target):
    if any(c.id == id for c in COMMANDS):
        raise ValueError("duplicate command id")
    COMMANDS.append(Command(id, context, label, tuple(keys), target))


for name, label, keys, target in [
    ("palette", "Command palette", ["p"], "p"),
    ("assistant", "Command assistant", ["a"], "a"),
    ("agent", "Split OpenCode", ["g"], "g"),
    ("switch", "Switch window / session", ["s"], "s"),
    ("help", "Context help", ["question_mark"], "question_mark"),
    ("detach", "Detach", ["d"], "d"),
    ("new_window", "New window", ["c"], "c"),
    (
        "split_horizontal",
        "Split left / right",
        ["percent_sign", "vertical_line"],
        "percent_sign",
    ),
    (
        "split_vertical",
        "Split top / bottom",
        ["quotation_mark", "minus"],
        "quotation_mark",
    ),
    ("next_window", "Next window", ["n"], "n"),
    ("previous_window", "Previous window", ["b"], "b"),
    ("next_pane", "Next pane", ["o"], "o"),
    ("zoom", "Zoom pane", ["z"], "z"),
    ("notifications", "Notification actions", ["N"], "N"),
    *[(f"focus_{d}", f"Focus {d}", [d], d) for d in ("up", "down", "left", "right")],
    *[
        (f"resize_{d}", f"Resize {d}", [k], k)
        for d, k in [("left", "H"), ("down", "J"), ("up", "K"), ("right", "L")]
    ],
    *[(f"window_{i}", f"Select window {i}", [str(i)], str(i)) for i in range(10)],
]:
    register(
        "workspace." + name, "workspace", label, ["leader+" + k for k in keys], target
    )
for name, label, keys, target in [
    ("generate", "Generate command", ["enter"], "submit"),
    ("edit", "Native Bash editing", ["tab", "shift+tab"], "edit"),
    ("cancel", "Cancel / close", ["escape", "ctrl+c", "ctrl+q"], "cancel"),
    ("agent", "Open full Agent", ["ctrl+g"], "agent"),
    ("history_previous", "Previous request", ["up"], "recall(-1)"),
    ("history_next", "Next request", ["down"], "recall(1)"),
    ("action_left", "Previous action", ["left"], "cycle(-1)"),
    ("action_right", "Next action", ["right"], "cycle(1)"),
    ("actions", "Actions / run current command", ["leader+full_stop"], "actions"),
]:
    register("assistant." + name, "assistant", label, keys, target)
for name, label, keys, target in [
    ("close", "Close viewer", ["q", "escape"], "q"),
    ("zoom_in", "Zoom in", ["plus", "equals_sign"], "+"),
    ("zoom_out", "Zoom out", ["minus"], "-"),
    ("fit", "Fit", ["0"], "0"),
    ("thumbnails", "Toggle thumbnails", ["t"], "t"),
    ("previous", "Previous page / image", ["left_square_bracket"], "["),
    ("next", "Next page / image", ["right_square_bracket"], "]"),
    ("search", "Search PDF", ["slash"], "/"),
    ("help", "Viewer help", ["question_mark"], "?"),
    *[(d, "Pan " + d, [d], d) for d in ("up", "down", "left", "right")],
]:
    register("viewer." + name, "viewer", label, keys, target)
for context in ("palette", "switch", "menu", "help", "about", "key_settings"):
    actions = [("close", "Back / close", "escape")]
    if context not in ("help", "about"):
        actions.insert(0, ("choose", "Choose", "enter"))
    if context in ("palette", "switch", "menu"):
        actions = [
            ("previous", "Previous item", "up"),
            ("next", "Next item", "down"),
        ] + actions
    for name, label, key in actions:
        register(context + "." + name, context, label, [key], key)


def bindings(command, settings):
    return tuple(settings.get("keybindings", {}).get(command.id, command.keys))


def resolve(context, key, settings):
    matches = [
        c
        for c in COMMANDS
        if c.context == context
        or key.startswith("leader+")
        and c.context == "workspace"
    ]
    return next((c for c in matches if key in bindings(c, settings)), None)


def default_reserved(context, key):
    return any(c.context == context and key in c.keys for c in COMMANDS)


def validate(overrides):
    unknown = set(overrides) - {c.id for c in COMMANDS}
    if unknown:
        raise ValueError("Unknown commands: " + ", ".join(sorted(unknown)))
    seen = {}
    for c in COMMANDS:
        for key in overrides.get(c.id, c.keys):
            if not key or any(ch.isspace() for ch in key):
                raise ValueError("Use normalized keys such as leader+p or ctrl+g")
            scope = "leader" if key.startswith("leader+") else c.context
            if (scope, key) in seen:
                raise ValueError(f"{key} conflicts with {seen[scope, key]}")
            seen[scope, key] = c.id


def help_rows(context, settings):
    names = {
        "quotation_mark": '"',
        "percent_sign": "%",
        "vertical_line": "|",
        "full_stop": ".",
        "question_mark": "?",
        "minus": "-",
        "plus": "+",
        "slash": "/",
        "equals_sign": "=",
    }

    def show(key):
        parts = key.split("+")
        return (
            ("Leader " + names.get(parts[-1], parts[-1]))
            if key.startswith("leader+")
            else "+".join(names.get(p, p) for p in parts)
        )

    return [
        (" / ".join(show(k) for k in bindings(c, settings)), c.label)
        for c in COMMANDS
        if c.context == context
    ]


for name, label, keys, target in [
    ("choose", "Run selected action", ["enter"], "submit"),
    ("close", "Return to request", ["escape", "ctrl+c", "ctrl+q"], "cancel"),
    ("edit", "Native Bash editing", ["tab", "shift+tab"], "edit"),
    ("left", "Previous action", ["left"], "cycle(-1)"),
    ("right", "Next action", ["right"], "cycle(1)"),
    ("agent", "Open full Agent", ["ctrl+g"], "agent"),
]:
    register("assistant_actions." + name, "assistant_actions", label, keys, target)
for name, label, key in [
    ("accept", "Apply search", "enter"),
    ("cancel", "Cancel search", "escape"),
    ("delete", "Delete character", "backspace"),
]:
    register("viewer_search." + name, "viewer_search", label, [key], key)
register("surface.close", "surface", "Close Mod view", ["escape"], "escape")
