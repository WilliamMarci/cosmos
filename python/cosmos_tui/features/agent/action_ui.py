"""Expose current UI commands through the same dispatcher as the action drawer."""

from cosmos_tui.input import keymap
from cosmos_tui.core import rpc


def catalog(app, category=None):
    context = app.key_context()
    commands = [
        c for c in keymap.COMMANDS if c.context == context or c.context == "global"
    ]
    return dict(
        client=app.client,
        context=context,
        active_pane=app.active().id if app.active() else None,
        actions=[
            dict(id=c.id, label=c.label, scope="ui", context=c.context)
            for c in commands
            if category is None or c.id.startswith(category)
        ],
    )


async def handle(app, request):
    if request.get("client") != app.client:
        raise ValueError("request targets a different UI client")
    if request.get("operation") == "list":
        return catalog(app, request.get("category"))
    if request.get("operation") == "reader_events":
        from cosmos_tui.features.agent.terminal import TerminalTools

        identity = request.get("request_id")
        if not isinstance(identity, str):
            raise ValueError("request_id must be a string")
        record = app.reader_ui.events.requests.get(identity)
        if record is None:
            raise ValueError("Reader request is unknown or expired")
        await TerminalTools(app.backend.argv[2]).pane(record["pane"])
        current = next((p for p in app.panes if p.id == record["pane"]), None)
        app.reader_ui.events.replaced(
            record["pane"], current.viewer if current else None
        )
        event = await app.reader_ui.events.result(identity, request.get("wait_ms", 0))
        await TerminalTools(app.backend.argv[2]).pane(record["pane"])
        return event
    if request.get("operation") == "context":
        return dict(
            client=app.client,
            context=app.key_context(),
            active_pane=app.active().id if app.active() else None,
        )
    if request.get("operation") in ("focus", "open_file"):
        from cosmos_tui.features.agent.terminal import TerminalTools
        from cosmos_tui.terminal import targets

        if app.screen is not app._workspace_screen:
            raise ValueError("Close the current UI dialog before switching sessions")
        row = await TerminalTools(app.backend.argv[2]).pane(request.get("pane"))
        state = None
        kind = None
        if request["operation"] == "open_file":
            from pathlib import Path
            from cosmos_tui.features.reader.opener import SUPPORTED

            raw = request.get("path")
            if not isinstance(raw, str) or not raw:
                raise ValueError("path must be a nonempty local file or directory")
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = Path(row["pane_current_path"]) / path
            path = path.resolve(strict=True)
            if path.is_dir():
                kind, state = "files", dict(kind="files", path=str(path), cursor=0)
            elif path.is_file() and path.suffix.lower() in SUPPORTED:
                kind = (
                    "image"
                    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                    else "document"
                )
                state = dict(path=str(path), page=0, zoom=1, pan=[0, 0])
            else:
                raise ValueError("unsupported Reader/Files format")
        await targets.select(
            app.backend,
            dict(
                kind="pane",
                pane_id=row["pane_id"],
                window_id=row["window_id"],
                session_id=row["session_id"],
                session=row["session_name"],
            ),
        )
        app.panes = await app.backend.snapshot()
        if state is not None:
            pane = next((p for p in app.panes if p.id == row["pane_id"]), None)
            if pane is None:
                raise ValueError("target pane disappeared before opening")
            await app.reader_ui.update_viewer(pane, state)
            request_id = app.reader_ui.events.begin(pane, state["path"])
            return dict(
                request_id=request_id,
                client=app.client,
                pane=row["pane_id"],
                display_id=row.get("display_id"),
                path=state["path"],
                view=kind,
                status="opened",
                loading="pending",
                complete=False,
            )
        return dict(
            context=app.key_context(),
            display_id=row.get("display_id"),
            client=app.client,
            pane=row["pane_id"],
            session=row["session_id"],
            status="selected",
        )
    if request.get("operation") == "menu":
        actions = await rpc.call("actions.list")
        row = next(
            (
                row
                for row in actions
                if row["id"] == request.get("id") and row.get("kind") == "menu"
            ),
            None,
        )
        if row is None:
            raise ValueError("unknown service menu action")
        await app.navigation.execute_entry(
            dict(kind="settings", menu=row["menu"]), app.screen
        )
        return dict(
            client=app.client,
            action=row["id"],
            status="dispatched",
            context=app.key_context(),
        )
    if request.get("operation") != "invoke":
        raise ValueError("unknown Action operation")
    params = request.get("params", {})
    if not isinstance(params, dict) or params:
        raise ValueError(
            "UI commands currently accept no params; operate in the listed client context"
        )
    available = catalog(app)
    if not any(row["id"] == request.get("id") for row in available["actions"]):
        raise ValueError(
            "Action is not available in the current UI context; refresh list_actions"
        )
    command = next(c for c in keymap.COMMANDS if c.id == request["id"])
    source = app.screen
    await app.navigation.execute_entry(dict(kind="command", command=command), source)
    return dict(
        client=app.client,
        action=command.id,
        status="dispatched",
        context=app.key_context(),
    )
