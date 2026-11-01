"""Shared tmux header reservation; no extra terminal writer or pane is created."""

import json
import subprocess

from cosmos_tui.features.agent.control import ControlStore

OPTION = "@cosmos_control_header"


def synchronize(argv):
    store = ControlStore(argv[2])

    def cli(*arguments):
        result = subprocess.run(
            [*argv, *arguments], capture_output=True, text=True, timeout=5
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Tmux header update failed")
        return result.stdout.strip()

    with store.locked(write=False) as state:
        panes = {}
        for line in cli(
            "list-panes", "-a", "-F", "#{pane_id}\t#{window_id}\t#{pid}"
        ).splitlines():
            pane, window, pid = line.split("\t")
            panes[pane] = (window, pid)
        visible = {
            pane: value
            for pane, value in state.items()
            if pane in panes and value.get("server_pid") == panes[pane][1]
        }
        from cosmos_tui.features.agent.tasks.storage import Tasks

        task_store = Tasks(argv[2])
        task_rows = task_store.list() if task_store.path.exists() else []
        visible_tasks = [
            row
            for row in task_rows
            if row["pane"] in panes
            and str(row["server_pid"]) == panes[row["pane"]][1]
            and row["state"] not in ("cancelled", "succeeded", "failed")
        ]
        records = {
            pane: dict(
                pane=pane,
                state=value["state"],
                task=value["task"],
                pointer=value.get("pointer"),
            )
            for pane, value in visible.items()
        }
        for row in visible_tasks:
            if row["pane"] in records:
                continue
            records[row["pane"]] = dict(
                pane=row["pane"],
                state=(
                    "paused"
                    if row["state"] in ("paused", "needs_review", "blocked")
                    else "active"
                ),
                task=row["goal"],
                pointer=None,
            )
        wanted = {panes[pane][0] for pane in records}
        windows = {}
        for line in cli(
            "list-windows", "-a", "-F", "#{window_id}\t#{" + OPTION + "}"
        ).splitlines():
            window, _, saved = line.partition("\t")
            windows[window] = saved
        for window, saved in windows.items():
            if window in wanted and not saved:
                previous = cli("show-options", "-w", "-t", window, "pane-border-status")
                previous = previous.partition(" ")[2] if previous else None
                cli(
                    "set-option",
                    "-w",
                    "-t",
                    window,
                    OPTION,
                    json.dumps(dict(previous=previous)),
                )
                try:
                    cli("set-option", "-w", "-t", window, "pane-border-status", "top")
                except Exception:
                    cli("set-option", "-wu", "-t", window, OPTION)
                    raise
            elif window in wanted and saved:
                if (
                    cli("show-options", "-Awv", "-t", window, "pane-border-status")
                    != "top"
                ):
                    cli("set-option", "-w", "-t", window, "pane-border-status", "top")
            elif window not in wanted and saved:
                previous = json.loads(saved)["previous"]
                if previous is None:
                    cli("set-option", "-wu", "-t", window, "pane-border-status")
                else:
                    cli(
                        "set-option", "-w", "-t", window, "pane-border-status", previous
                    )
                cli("set-option", "-wu", "-t", window, OPTION)
        return list(records.values())
