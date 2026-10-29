"""Expose current UI commands through the same dispatcher as the action drawer."""

from cosmos_tui.input import keymap
from cosmos_tui.core import rpc


def catalog(app):
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
        ],
    )


async def handle(app, request):
    if request.get("client") != app.client:
        raise ValueError("request targets a different UI client")
    if request.get("operation") == "list":
        return catalog(app)
    if request.get("operation") == "focus":
        from cosmos_tui.features.agent.terminal import TerminalTools
        from cosmos_tui.terminal import targets

        if app.screen is not app._workspace_screen:
            raise ValueError("Close the current UI dialog before switching sessions")
        row = await TerminalTools(app.backend.argv[2]).pane(request.get("pane"))
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
        return dict(
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
