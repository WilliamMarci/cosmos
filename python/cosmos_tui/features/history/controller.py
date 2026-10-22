from __future__ import annotations

from cosmos_tui.core.controller import Controller
from cosmos_tui.features.search.bar import BottomSearch


class HistoryController(Controller):
    async def copy_action(self, command):
        app = self.app
        pane = app.active()
        if not pane or not pane.copy_mode:
            return
        if command in ("search", "search_backward"):
            pid = pane.id
            backward = command == "search_backward"
            last_query = None

            async def search(query, step):
                nonlocal last_query
                if not any(p.id == pid and p.copy_mode for p in app.panes):
                    raise RuntimeError("Source history pane is no longer available")
                if not query:
                    return "Enter a query"
                if step and query == last_query:
                    action = "search-again" if step > 0 else "search-reverse"
                    await app.backend.request(f"send-keys -X -t {pid} {action}")
                else:
                    direction = "search-backward" if backward else "search-forward"
                    await app.backend.request(
                        f"send-keys -X -t {pid} {direction} {app.backend.quote(query)}"
                    )
                last_query = query
                app.panes = await app.backend.snapshot()
                result = await app.backend.request(
                    f"display-message -p -t {pid} '#{{search_count_current}}/#{{search_count}}'"
                )
                return result[0] if result else "History"

            app.push_screen(BottomSearch("History", search, steps=True))
            return
        try:
            await app.backend.request(f"send-keys -X -t {pane.id} {command}")
            app.panes = await app.backend.snapshot()
        except RuntimeError as error:
            await app.action_error("history", error)

    async def scroll_history(self, event, up):
        app = self.app
        if app.screen is not app._workspace_screen or app.views:
            return
        pane = next(
            (
                p
                for p in app.panes
                if p.x <= event.screen_x < p.x + p.width
                and p.y <= event.screen_y < p.y + p.height
            ),
            None,
        )
        if not pane or pane.viewer or not up and not pane.copy_mode:
            return
        try:
            if not pane.active:
                await app.backend.request(f"select-pane -t {pane.id}")
            if not pane.copy_mode:
                await app.backend.request(f"copy-mode -t {pane.id}")
            await app.backend.request(
                f"send-keys -X -N 3 -t {pane.id} {'scroll-up' if up else 'scroll-down'}"
            )
            app.panes = await app.backend.snapshot()
            event.stop()
        except RuntimeError as error:
            await app.action_error("history scroll", error)
