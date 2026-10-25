"""Functional grouping shared by keybinding settings."""

GROUPS = [
    "General & menus",
    "Sessions & windows",
    "Panes & layout",
    "History & selection",
    "Command assistant",
    "Reader",
    "Files",
    "Mods",
    "Input method",
    "Dialogs & settings",
]


def group(command):
    name, context = command.id, command.context
    if context == "switch":
        return "Sessions & windows"
    if context.startswith("mod."):
        return "Mods"
    if ".ime_" in name:
        return "Input method"
    if context.startswith("assistant") or name in (
        "workspace.assistant",
        "workspace.agent",
    ):
        return "Command assistant"
    if context == "files" or name == "workspace.files":
        return "Files"
    if context.startswith("viewer"):
        return "Reader"
    if context == "copy" or any(
        x in name for x in ("history", "copy_mode", "paste_buffer")
    ):
        return "History & selection"
    if any(
        x in name
        for x in ("split_", "focus_", "resize_", "next_pane", "identify_panes", ".zoom")
    ):
        return "Panes & layout"
    if any(
        x in name
        for x in ("window_", "new_window", "new_session", ".switch", ".detach", ".quit")
    ):
        return "Sessions & windows"
    if context in ("workspace", "global"):
        return "General & menus"
    return "Dialogs & settings"
