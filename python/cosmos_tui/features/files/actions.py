"""File commands orchestrate pure operations, shared dialogs and host services."""

import asyncio
import os
import shutil
from pathlib import Path
from cosmos_tui.features.files import operations
from cosmos_tui.ui.menus import CompactMenu
from cosmos_tui.ui.text_prompt import TextPrompt as FilePrompt


def launch(manager, pane, state, title, function, *args):
    app = manager.controller.app
    if manager.busy:
        app.run_worker(
            app.action_error("files", RuntimeError("A file operation is still running"))
        )
        return
    manager.busy = True
    source_path = state["path"]

    async def run():
        try:
            await asyncio.to_thread(function, *args)
            manager.snapshots.clear()
            if pane.viewer:
                current = manager.controller.state(pane)
                if current.get("kind") == "files" and current["path"] == source_path:
                    current.update(selected=[], cursor=0)
                    await manager.controller.update_viewer(pane, current)
            await app.notification_events.publish(
                title, source="files", level="success"
            )
        except (OSError, ValueError, RuntimeError) as error:
            manager.snapshots.clear()
            await app.action_error("files", error)
        finally:
            manager.busy = False

    app.run_worker(run(), name="files.operation")


async def handle(manager, event, pane, state, items, cursor):
    key, char = event.key, event.character
    app = manager.controller.app
    selected = set(state.get("selected", []))
    targets = [item["path"] for item in items if item["path"] in selected]
    if not targets and items:
        targets = [items[cursor]["path"]]
    if key == "space":
        if items:
            target = items[cursor]["path"]
            selected.symmetric_difference_update({target})
            state["selected"] = sorted(selected)
            state["cursor"] = min(len(items) - 1, cursor + 1)
            await manager.controller.update_viewer(pane, state)
    elif char == "V":
        state["selected"] = (
            [] if len(selected) == len(items) else [i["path"] for i in items]
        )
        await manager.controller.update_viewer(pane, state)
    elif char in ("y", "x"):
        if targets:
            manager.clipboard = (tuple(targets), char == "x")
            await app.notification_events.publish(
                f"{len(targets)} item(s) marked for {'move' if char == 'x' else 'copy'}",
                source="files",
            )
    elif char == "p":
        if not manager.clipboard:
            raise ValueError("No files in the file clipboard")
        sources, move = manager.clipboard

        def paste():
            operations.transfer(sources, state["path"], move)
            if move and manager.clipboard == (sources, move):
                manager.clipboard = None

        launch(manager, pane, state, "Files moved" if move else "Files copied", paste)
    elif char in ("a", "A", "r"):
        if char == "r" and not items:
            return True
        source = items[cursor]["path"] if items else None

        async def submit(name, _):
            if char == "r":
                launch(manager, pane, state, "Renamed", operations.rename, source, name)
            else:
                launch(
                    manager,
                    pane,
                    state,
                    "Created",
                    operations.create,
                    state["path"],
                    name,
                    char == "A",
                )

        app.push_screen(
            FilePrompt(
                "Rename"
                if char == "r"
                else "New directory"
                if char == "A"
                else "New file",
                submit,
                initial=Path(source).name if char == "r" else "",
                bounds=lambda: manager.controller.pane_bounds(pane.id, state["path"]),
            )
        )
    elif char == "d":
        if targets:

            def confirm(result):
                if result == "trash":
                    launch(
                        manager,
                        pane,
                        state,
                        "Moved to Trash",
                        operations.trash,
                        tuple(targets),
                    )

            app.push_screen(
                CompactMenu(
                    f"Trash {len(targets)} item(s)?",
                    [("cancel", "Cancel"), ("trash", "Move to Trash")],
                ),
                confirm,
            )
    elif key == "file_category":
        choices = [
            (name, label)
            for name, label in (
                ("all", "All files"),
                ("directory", "Directories"),
                ("image", "Images"),
                ("document", "Documents"),
                ("archive", "Archives"),
                ("media", "Audio / video"),
                ("code", "Source / config"),
                ("executable", "Executables"),
                ("link", "Symbolic links"),
                ("file", "Other files"),
            )
        ]

        def choose_category(value):
            if value:
                state.update(category=value, cursor=0)
                app.run_worker(manager.controller.update_viewer(pane, state))

        app.push_screen(CompactMenu("Filter by type", choices), choose_category)
    elif char == "S":
        choices = [
            (value, label)
            for value, label in [
                ("natural", "Natural name"),
                ("size", "Size"),
                ("mtime", "Modified time"),
                ("extension", "Extension"),
            ]
        ]

        def choose(value):
            if value:
                state.update(sort=value, cursor=0)
                app.run_worker(manager.controller.update_viewer(pane, state))

        app.push_screen(CompactMenu("Sort files", choices), choose)
    elif char == "R":
        state["reverse"] = not state.get("reverse", False)
        await manager.controller.update_viewer(pane, state)
    elif char in ("t", "g"):
        executable = (
            shutil.which(os.getenv("COSMOS_OPENCODE", "opencode"))
            if char == "g"
            else None
        )
        if char == "g" and not executable:
            raise RuntimeError("OpenCode not found on PATH")
        await app.session_windows.open(
            (executable,) if executable else (),
            name="agent" if char == "g" else None,
            cwd=state["path"],
        )
    elif key == "ctrl+r":
        manager.snapshots.clear()
        await manager.controller.update_viewer(pane, state)
    else:
        return False
    return True


def command_group(command):
    name = command.id.split(".")[-1]
    if name in (
        "copy",
        "cut",
        "paste",
        "create",
        "mkdir",
        "rename",
        "trash",
        "select",
        "select_all",
    ):
        return "Files / Operations"
    if name in ("sort", "sort_menu", "reverse"):
        return "Files / Sorting"
    if name in ("filter", "hidden", "category"):
        return "Files / Filters"
    if name in ("terminal", "agent"):
        return "Files / Open here"
    return "Files / Navigation"
