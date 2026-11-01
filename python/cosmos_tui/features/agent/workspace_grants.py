"""Conversation-local workspace capabilities, excluding terminal input/destruction."""

import secrets


class WorkspaceGrants:
    async def acquire_workspace(self, task):
        if (
            not isinstance(task, str)
            or not 1 <= len(task) <= 120
            or not task.isprintable()
        ):
            raise ValueError("task must be printable, 1–120 characters")
        token, task_id = secrets.token_urlsafe(32), secrets.token_hex(16)
        self._workspace_grants = {token: task_id}
        return dict(
            token=token,
            task=task,
            task_id=task_id,
            state="active",
            scope="workspace",
            capabilities=[
                "create_terminal",
                "create_session",
                "rename_target",
                "focus_pane",
            ],
        )

    def check_workspace(self, token):
        if token is not None and (
            not isinstance(token, str)
            or token not in getattr(self, "_workspace_grants", {})
        ):
            raise ValueError("Stale workspace token; acquire a new workspace task")

    async def release_workspace(self, token):
        self.check_workspace(token)
        if token is None:
            raise ValueError("workspace token is required")
        del self._workspace_grants[token]
        return dict(state="ended", scope="workspace")
