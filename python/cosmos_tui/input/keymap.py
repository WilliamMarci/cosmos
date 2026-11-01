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
    ("palette", "Settings panel", ["p"], "p"),
    ("assistant", "Command assistant", ["a"], "a"),
    ("agent", "Split Cosmos Agent", ["g"], "g"),
    ("switch", "Switch window / session", ["s"], "s"),
    ("files", "Open files", [], "files"),
    ("help", "Context help", ["question_mark"], "question_mark"),
    ("detach", "Detach", ["d"], "d"),
    ("copy_mode", "Select / scroll history", ["left_square_bracket"], "copy_mode"),
    ("history_search", "Search pane history", ["slash"], "history_search"),
    ("paste_buffer", "Paste Tmux selection", ["right_square_bracket"], "paste_buffer"),
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
    ("identify_panes", "Show pane numbers / select pane", ["q"], "identify_panes"),
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
register("global.actions", "global", "Context actions", ["ctrl+p"], "actions")
register(
    "global.keyboard_passthrough",
    "global",
    "Toggle keyboard passthrough",
    ["leader+f12"],
    "keyboard_passthrough",
)
register(
    "global.ime_toggle",
    "global",
    "Input language · Chinese / English",
    ["leader+i"],
    "ime_toggle",
)
register("global.ime_width", "global", "Input width · Half / Full", [], "ime_width")
register("global.ime_enable", "global", "Enable IME", [], "ime_enable")
register("global.ime_disable", "global", "Disable IME", [], "ime_disable")
register("workspace.quit", "workspace", "Quit / Exit Cosmos", [], "quit")
for target, label in (
    ("resume_control", "Resume pane Agent control"),
    ("end_control", "End pane Agent control"),
):
    register("workspace." + target, "workspace", label, [], target)
for target, label, keys in (
    ("pause", "Pause task", ["p"]),
    ("resume", "Resume task", ["r"]),
    ("check", "Check task now", ["c"]),
    ("more", "Task options", ["enter"]),
    ("controls", "Pane controls", []),
    ("history", "Task run history", []),
    ("reschedule", "Reschedule task", []),
    ("mode", "Toggle task wake mode", []),
    ("permissions", "Task pending permissions", []),
    ("cancel_task", "Cancel Agent task", []),
    ("interrupt_program", "Interrupt task terminal program", []),
    ("cancel", "Close Tasks", ["escape", "q"]),
):
    register("tasks." + target, "tasks", label, keys, "task_" + target)
register("workspace.tasks", "workspace", "Agent tasks", [], "tasks")
register("workspace.new_session", "workspace", "New session", [], "new_session")
register(
    "workspace.private_pane",
    "workspace",
    "Toggle private pane · Agent access",
    [],
    "private_pane",
)
register(
    "workspace.mouse_passthrough",
    "workspace",
    "Toggle mouse passthrough",
    [],
    "mouse_passthrough",
)
register("global.start", "global", "Start menu", ["leader+m"], "start")
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
    ("fit", "Fit page", ["0", "space"], "0"),
    ("thumbnails", "Toggle thumbnails", ["t"], "t"),
    ("previous", "Previous page / image", ["left_square_bracket", "comma"], "["),
    ("next", "Next page / image", ["right_square_bracket", "full_stop"], "]"),
    ("search", "Search document", ["slash"], "/"),
    ("jump", "Go to page", ["g"], "g"),
    ("find_next", "Next document match", ["n"], "n"),
    ("find_previous", "Previous document match", ["N"], "N"),
    ("outline", "Switch thumbnails / outline", ["o"], "o"),
    ("navigation_focus", "Next paragraph / focus outline", ["tab"], "tab"),
    ("paragraph_previous", "Previous paragraph", ["shift+tab"], "shift+tab"),
    ("reading_options", "Reading options", ["r"], "r"),
    ("columns", "Cycle rich document columns", ["c"], "c"),
    ("reading_mode", "Toggle paged / scroll reading", ["v"], "v"),
    ("inspect", "Open selected image / table", ["enter"], "enter"),
    ("copy_asset", "Copy selected image / table", ["y"], "y"),
    ("fold_asset", "Fold selected inline image", ["f"], "f"),
    ("help", "Viewer help", ["question_mark"], "?"),
    *[
        (d, "Pan " + d, [d, k], d)
        for d, k in (("up", "k"), ("down", "j"), ("left", "h"), ("right", "l"))
    ],
]:
    register("viewer." + name, "viewer", label, keys, target)
for name, label, keys, target in [
    ("close", "Close files", ["q", "escape"], "q"),
    ("open", "Open entry", ["enter", "right", "l"], "enter"),
    ("parent", "Parent directory", ["left"], "left"),
    ("up", "Previous entry", ["up", "k"], "up"),
    ("down", "Next entry", ["down", "j"], "down"),
    ("first", "First entry", ["home"], "home"),
    ("last", "Last entry", ["end"], "end"),
    ("page_up", "Previous page", ["pageup"], "pageup"),
    ("page_down", "Next page", ["pagedown"], "pagedown"),
    ("filter", "Filter files", ["slash"], "/"),
    ("category", "Filter files by type", [], "file_category"),
    ("hidden", "Toggle hidden files", ["h", "full_stop"], "."),
    ("sort", "Cycle sort order", ["s"], "s"),
    ("sort_menu", "Choose sort order", ["S"], "S"),
    ("reverse", "Reverse sort direction", ["R"], "R"),
    ("select", "Toggle selection", ["space"], "space"),
    ("select_all", "Toggle all visible entries", ["V"], "V"),
    ("copy", "Copy selected files", ["y"], "y"),
    ("cut", "Cut selected files", ["x"], "x"),
    ("paste", "Paste files here", ["p"], "p"),
    ("create", "Create file", ["a"], "a"),
    ("mkdir", "Create directory", ["A"], "A"),
    ("rename", "Rename entry", ["r"], "r"),
    ("trash", "Move selected files to Trash", ["d"], "d"),
    ("terminal", "Open terminal here", ["t"], "t"),
    ("agent", "Open Agent here", ["g"], "g"),
    ("refresh", "Refresh files", ["ctrl+r"], "ctrl+r"),
    ("help", "Files help", ["question_mark"], "?"),
]:
    register("files." + name, "files", label, keys, target)
for context in (
    "palette",
    "switch",
    "menu",
    "help",
    "about",
    "key_settings",
    "action_drawer",
    "start_menu",
):
    actions = [("close", "Back / close", "escape")]
    if context not in ("help", "about"):
        actions.insert(0, ("choose", "Choose", "enter"))
    if context in ("palette", "switch", "menu", "action_drawer", "start_menu"):
        actions = [
            ("previous", "Previous item", "up"),
            ("next", "Next item", "down"),
        ] + actions
    for name, label, key in actions:
        register(
            context + "." + name,
            context,
            label,
            [key, "q", "comma"]
            if name == "close" and context == "about"
            else [key, "q"]
            if name == "close" and context == "palette"
            else [key],
            key,
        )

for name, label, key in [
    ("expand", "Expand session / window", "right"),
    ("collapse", "Collapse session / window", "left"),
    ("new", "New session", "ctrl+n"),
    ("rename", "Rename selected target", "ctrl+r"),
    ("more", "More target actions", "ctrl+o"),
]:
    register("switch." + name, "switch", label, [key], key)

for name, label, keys, target in [
    ("cancel", "Return to terminal", ["escape", "q"], "cancel"),
    (
        "select",
        "Begin selection",
        ["space", "v", "ctrl+space", "ctrl+@"],
        "begin-selection",
    ),
    ("clear", "Clear selection", ["ctrl+g"], "clear-selection"),
    (
        "copy",
        "Copy selection to Tmux buffer",
        ["enter", "y", "alt+w"],
        "copy-selection-and-cancel",
    ),
    ("page_up", "Previous history page", ["pageup"], "page-up"),
    ("page_down", "Next history page", ["pagedown", "ctrl+f"], "page-down"),
    ("top", "Oldest retained output", ["home", "g"], "history-top"),
    ("bottom", "Latest output", ["end", "G"], "history-bottom"),
    ("line_start", "Start of line", ["0", "ctrl+a"], "start-of-line"),
    ("line_end", "End of line", ["dollar_sign", "ctrl+e"], "end-of-line"),
    ("word_next", "Next word", ["w"], "next-word"),
    ("word_previous", "Previous word", ["b"], "previous-word"),
    ("search", "Search history forward", ["slash", "ctrl+s"], "search"),
    (
        "search_backward",
        "Search history backward",
        ["question_mark", "ctrl+r"],
        "search_backward",
    ),
    ("next", "Next match", ["n"], "search-again"),
    ("previous", "Previous match", ["N"], "search-reverse"),
    *[
        (d, "Move " + d, [d, k], "cursor-" + d)
        for d, k in (("left", "h"), ("down", "j"), ("up", "k"), ("right", "l"))
    ],
]:
    register("copy." + name, "copy", label, keys, target)
register(
    "history_search.close", "history_search", "Cancel search", ["escape"], "escape"
)
register("history_search.choose", "history_search", "Search", ["enter"], "enter")


LEADERS = {"leader": "C-b", "leader2": "C-a", "leader3": "C-m"}


def leader_chords(settings):
    return {
        name: value.replace("C-", "ctrl+")
        for name, default in LEADERS.items()
        if (value := settings.get(name, default)) != "off"
    }


def active_leader_chords(settings):
    used = {
        prefix_name(key) for command in COMMANDS for key in bindings(command, settings)
    }
    return {
        name: chord
        for name, chord in leader_chords(settings).items()
        if name == "leader" or name in used
    }


def prefix_name(key):
    name = key.partition("+")[0]
    return name if name in LEADERS and "+" in key else None


def bindings(command, settings):
    return tuple(settings.get("keybindings", {}).get(command.id, command.keys))


def resolve(context, key, settings):
    matches = [
        c
        for c in COMMANDS
        if c.context in (context, "global")
        or prefix_name(key)
        and c.context == "workspace"
    ]
    return next((c for c in matches if key in bindings(c, settings)), None)


def default_reserved(context, key):
    return any(c.context == context and key in c.keys for c in COMMANDS)


def validate(overrides, settings=None):
    chords = leader_chords(settings or {})
    unknown = {
        name
        for name in set(overrides) - {c.id for c in COMMANDS}
        if not name.startswith("mod.")
    }
    if unknown:
        raise ValueError("Unknown commands: " + ", ".join(sorted(unknown)))
    seen = {}
    for c in COMMANDS:
        for key in overrides.get(c.id, c.keys):
            if not key or any(ch.isspace() for ch in key):
                raise ValueError("Use normalized keys such as leader+p or ctrl+g")
            prefix = prefix_name(key)
            scope = "prefix:" + chords.get(prefix, prefix) if prefix else c.context
            checked_key = key.partition("+")[2] if prefix else key
            if (scope, checked_key) in seen:
                raise ValueError(f"{key} conflicts with {seen[scope, checked_key]}")
            seen[scope, checked_key] = c.id
    global_keys = {
        key: owner for (scope, key), owner in seen.items() if scope == "global"
    }
    for (scope, key), owner in seen.items():
        if scope != "global" and key in global_keys:
            raise ValueError(f"{key} conflicts with global command {global_keys[key]}")


def display_binding(key, settings):
    names = {
        "quotation_mark": '"',
        "percent_sign": "%",
        "vertical_line": "|",
        "full_stop": ".",
        "comma": ",",
        "space": "Space",
        "ctrl": "Ctrl",
        "alt": "Alt",
        "shift": "Shift",
        "left_square_bracket": "[",
        "right_square_bracket": "]",
        "question_mark": "?",
    }
    prefix = prefix_name(key)
    if prefix:
        leader = leader_chords(settings).get(prefix, "off").replace("ctrl+", "Ctrl+")
        if leader.startswith("Ctrl+"):
            leader = "Ctrl+" + leader[5:].upper()
        return leader + " → " + display_binding(key.partition("+")[2], settings)
    return "+".join(names.get(part, part) for part in key.split("+"))


def help_rows(context, settings):
    names = {
        "quotation_mark": '"',
        "percent_sign": "%",
        "vertical_line": "|",
        "full_stop": ".",
        "comma": ",",
        "space": "Space",
        "left_square_bracket": "[",
        "right_square_bracket": "]",
        "question_mark": "?",
        "minus": "-",
        "plus": "+",
        "slash": "/",
        "equals_sign": "=",
    }

    def show(key):
        parts = key.split("+")
        return (
            (parts[0].title() + " " + names.get(parts[-1], parts[-1]))
            if prefix_name(key)
            else "+".join(names.get(p, p) for p in parts)
        )

    return [
        (" / ".join(show(k) for k in bindings(c, settings)), c.label)
        for c in COMMANDS
        if c.context in (context, "global")
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

for name, label, keys, target in [
    ("close", "Close content search", ["escape"], "close"),
    ("submit", "Search content", ["enter"], "submit"),
    ("next", "Next match", ["f3"], "next"),
    ("previous", "Previous match", ["shift+f3"], "previous"),
]:
    register("content_search." + name, "content_search", label, keys, target)

for name, label, key in [
    ("scroll_up", "Previous shortcut", "up"),
    ("scroll_down", "Next shortcut", "down"),
    ("first", "First shortcut", "home"),
    ("last", "Last shortcut", "end"),
    ("page_up", "Previous shortcut page", "pageup"),
    ("page_down", "Next shortcut page", "pagedown"),
]:
    register("help." + name, "help", label, [key], key)

for name, label, key in [
    ("next", "Next theme control", "tab"),
    ("previous", "Previous theme control", "shift+tab"),
    ("save", "Save themes", "ctrl+s"),
    ("cancel", "Cancel theme selection", "escape"),
]:
    register(
        "theme_settings." + name,
        "theme_settings",
        label,
        [key, "q", "comma"] if name == "cancel" else [key],
        key,
    )

register("page_jump.submit", "page_jump", "Go to page", ["enter"], "enter")
register("page_jump.cancel", "page_jump", "Cancel page jump", ["escape"], "escape")

register(
    "palette.cycle_previous",
    "palette",
    "Previous setting value",
    ["left"],
    "cycle_previous",
)
register("palette.cycle_next", "palette", "Next setting value", ["right"], "cycle_next")
register("palette.parent", "palette", "Parent settings menu", ["comma"], "parent")
register("palette.child", "palette", "Open settings submenu", ["full_stop"], "child")
