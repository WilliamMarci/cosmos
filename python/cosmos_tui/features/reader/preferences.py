"""Reader defaults and context-specific action availability."""

from pathlib import Path
from cosmos_tui.features.reader.documents import FORMATS


def defaults(state, settings):
    if Path(state["path"]).suffix.lower() in FORMATS:
        state.setdefault("columns", settings.get("viewer_rich_columns", "auto"))
        if state["columns"] != "auto":
            state["columns"] = int(state["columns"])
        state.setdefault("reading_mode", settings.get("viewer_rich_mode", "pages"))
        # Rendering limits follow current settings; columns/mode are pane overrides.
        state["image_rows"] = state.get(
            "inline_rows", settings.get("viewer_inline_image_rows", 8)
        )
        state.setdefault("line_space", 1)
        state["icon_edge"] = settings.get("viewer_icon_max_px", 64)
    return state


def commands(controller, pane, candidates):
    if not pane or not pane.viewer:
        return candidates
    state = controller.state(pane)
    rich = Path(state["path"]).suffix.lower() in FORMATS
    rich_only = {
        "reading_options",
        "columns",
        "reading_mode",
        "paragraph_previous",
        "inspect",
        "copy_asset",
        "fold_asset",
    }
    if not rich:
        return [
            c
            for c in candidates
            if c.context != "viewer" or c.id.split(".")[-1] not in rich_only
        ]
    inspector = state.get("inspector")
    selected = inspector if inspector is not None else state.get("selected_block")
    source = (
        next(
            (
                r
                for r in controller.documents.rows(state["path"])
                if r.block == selected
            ),
            None,
        )
        if selected is not None
        else None
    )
    if inspector is not None:
        available = {
            "close",
            "help",
            "copy_asset",
            "up",
            "down",
            "left",
            "right",
            "fit",
        }
        if source and source.image:
            available.update(("zoom_in", "zoom_out"))
    else:
        available = {
            "close",
            "help",
            "reading_options",
            "columns",
            "reading_mode",
            "previous",
            "next",
            "search",
            "jump",
            "find_next",
            "find_previous",
            "outline",
            "navigation_focus",
            "paragraph_previous",
            "up",
            "down",
            "left",
            "right",
        }
        if source:
            available.add("copy_asset")
            if source.image or source.table:
                available.add("inspect")
            if source.image:
                available.add("fold_asset")
    return [
        c
        for c in candidates
        if c.context != "viewer" or c.id.split(".")[-1] in available
    ]
