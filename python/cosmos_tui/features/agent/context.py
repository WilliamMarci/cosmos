"""Compact read-only workspace discovery, without enumerating action catalogs."""

import asyncio


class ContextTools:
    async def context(self, target=None, client=None):
        from cosmos_tui.features.agent.actions import ActionTools
        from cosmos_tui.features.agent.control import ControlStore

        rows = await self.panes()
        candidates = [
            dict(
                pane=r["pane_id"],
                display_id=r["display_id"],
                position=f"{r.get('window_index', '?')}:{r.get('pane_index', '?')}",
                session=r["session_name"],
                private=r["private"],
                pane_in_mode=r.get("pane_in_mode", False),
                alternate_screen=r.get("alternate_on", False),
                agent=r.get("agent", False),
            )
            for r in rows
        ]
        selected = None
        if target is not None:
            selected = next(
                (r for r in rows if target in (r["pane_id"], r["display_id"])), None
            )
        bridge = ActionTools(self.backend.argv[2])
        bridge.binding = self.binding
        clients = await bridge.clients()
        selected_client = (
            client
            if client in clients
            else (next(iter(clients)) if client is None and len(clients) == 1 else None)
        )
        view = None
        client_error = (
            "Client is no longer connected; choose from clients"
            if client is not None and client not in clients
            else None
        )
        if selected_client is not None:
            try:
                view = await bridge.client_context(selected_client)
            except (OSError, RuntimeError, TimeoutError) as error:
                client_error = self.redact(str(error))
        if client_error and selected_client is not None:
            clients.pop(selected_client, None)
            selected_client = None
        if target is None and view:
            active_pane = view.get("active_pane")
            selected = next((r for r in rows if r["pane_id"] == active_pane), None)
        tasks = await self.list_tasks() if getattr(self, "conversation", None) else []
        tasks = [
            dict(
                (k, r[k])
                for k in ("id", "pane", "state", "goal", "revision", "resume_challenge")
                if k in r
            )
            for r in tasks
            if r["state"] not in ("succeeded", "failed", "cancelled")
        ]

        def control_rows():
            with ControlStore(self.backend.argv[2]).locked(write=False) as state:
                return [
                    dict(
                        pane=p,
                        state=r["state"],
                        owned=r["owner"] == self.owner
                        and r["token"] == self.control_tokens.get(p),
                    )
                    for p, r in state.items()
                ]

        task_count = len(tasks)
        tasks.sort(
            key=lambda row: (
                row["state"] != "paused",
                row["pane"] != (selected or {}).get("pane_id"),
            )
        )
        visible_tasks = [dict(row, goal=row.get("goal", "")[:160]) for row in tasks[:8]]
        controls = await asyncio.to_thread(control_rows)
        pane = selected["pane_id"] if selected else None
        control = next((r for r in controls if r["pane"] == pane), None)
        paused = any(t["state"] == "paused" for t in tasks)
        if getattr(self, "conversation", None) and callable(
            getattr(self, "task_owner", None)
        ):
            from cosmos_tui.features.agent.tasks.storage import Tasks

            paused = paused or Tasks(self.backend.argv[2]).paused(self.conversation)
        owned = bool(pane and self.control_tokens.get(pane)) and (
            control is not None and control["state"] == "active" and control["owned"]
        )
        recent = None
        if selected and not selected["private"]:
            from cosmos_tui.features.agent.compact import compact_snapshot

            try:
                recent = compact_snapshot(
                    await self.observe(pane, ["text"]), max_bytes=1024, max_rows=8
                )
            except (OSError, RuntimeError, ValueError) as error:
                recent = dict(status="unavailable", message=self.redact(str(error)))
        recent_text = " ".join(
            str(row.get("text", "")) for row in (recent or {}).get("text", [])
        )
        recommended, automatic_skill = [], None
        if selected and not selected["private"]:
            from cosmos_tui.features.agent.skills import matching_skills, skill_body

            matched = matching_skills(
                selected.get("pane_current_command"),
                selected.get("pane_current_path"),
                recent_text,
            )
            recommended = [
                dict(
                    id=skill["id"],
                    name=skill["name"],
                    description=skill["description"],
                    reason=skill["reason"],
                    software=skill["software"],
                )
                for skill in matched
            ]
            if len(matched) == 1:
                identity = (
                    pane,
                    selected.get("pane_current_command"),
                    matched[0]["name"],
                )
                announced = getattr(self, "_announced_skills", None)
                if announced is None:
                    self._announced_skills = announced = set()
                if identity not in announced:
                    body = skill_body(matched[0])
                    automatic_skill = dict(
                        id=matched[0]["id"],
                        name=matched[0]["name"],
                        description=matched[0]["description"],
                        reason=matched[0]["reason"],
                        content=body["body"],
                        base=body["base"],
                        truncated=body["truncated"],
                        automatic=True,
                    )
                    announced.add(identity)
        target_data = (
            None
            if selected is None
            else dict(
                pane=pane,
                display_id=selected["display_id"],
                position=f"{selected.get('window_index', '?')}:{selected.get('pane_index', '?')}",
                private=selected["private"],
                agent=selected.get("agent", False),
                cwd=selected["pane_current_path"],
                program=selected["pane_current_command"],
                pane_in_mode=selected.get("pane_in_mode", False),
                alternate_screen=selected.get("alternate_on", False),
                screen=(
                    "copy"
                    if selected.get("pane_in_mode", False)
                    else "alternate"
                    if selected.get("alternate_on", False)
                    else "normal"
                ),
                recommended_skills=recommended or None,
                skill=automatic_skill,
            )
        )
        if target_data is not None:
            if not recommended:
                target_data.pop("recommended_skills")
            if automatic_skill is None:
                target_data.pop("skill")
        allowed = []
        if selected and not selected["private"]:
            allowed.append(dict(tool="cosmos_observe", target=pane))
            if owned and not paused:
                allowed.append(dict(tool="cosmos_step", target=pane))
            elif control and control["state"] == "paused":
                allowed.append(
                    dict(
                        tool="cosmos_control",
                        operation="begin",
                        target=pane,
                        takeover=True,
                    )
                )
                allowed.append(dict(tool="cosmos_control", operation="end", target=pane))
            elif not paused and not control:
                allowed.append(dict(tool="cosmos_control", operation="begin", target=pane))
        resume = next(
            (
                row
                for row in tasks
                if row["state"] == "paused" and "resume_challenge" in row
            ),
            None,
        )
        if resume:
            allowed.append(dict(tool="cosmos_task", operation="resume", task=resume))
        status = (
            "target_not_found"
            if target is not None and selected is None
            else "private"
            if selected and selected["private"]
            else "paused"
            if paused or control and control["state"] == "paused"
            else "controlled"
            if owned
            else "owned_by_other"
            if control
            else "ready"
        )
        return dict(
            status=status,
            paused=paused,
            control=(
                None
                if control is None
                else dict(state=control["state"], owned=control["owned"])
            ),
            allowed_next=allowed,
            recent=recent,
            target=target_data,
            targets=candidates if selected is None else None,
            clients=list(clients),
            client=selected_client,
            view=view,
            client_error=client_error,
            tasks=visible_tasks,
            task_count=task_count,
            tasks_truncated=task_count > len(visible_tasks),
            next=(
                "select_target"
                if selected is None
                else "request_resume"
                if status == "paused" and resume
                else "takeover_or_end_control"
                if status == "paused"
                else "observe_then_acquire_control"
                if status == "ready"
                else "observe"
                if status == "controlled"
                else "select_valid_target_or_wait"
            ),
        )
