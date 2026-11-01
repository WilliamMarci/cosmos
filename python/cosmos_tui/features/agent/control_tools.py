"""MCP-facing control lifecycle; terminal transport remains in TerminalTools."""

import asyncio


class ControlledInput:
    async def input_dispatch(
        self, pane, method, arguments, token=None, snapshot_id=None
    ):
        from cosmos_tui.features.agent.control import ControlStore

        await self.pane(pane)
        if getattr(self, "conversation", None):
            from cosmos_tui.features.agent.tasks.storage import Tasks

            if Tasks(self.backend.argv[2]).paused(self.conversation):
                raise ValueError("Conversation paused by user input")
        store = ControlStore(self.backend.argv[2])

        async def deliver():
            if token is not None:
                row = await self.pane(pane)
                expected = self.control_geometry.get(token)
                actual = tuple(
                    row[k] for k in ("pid", "window_id", "pane_width", "pane_height")
                )
                if expected != actual:
                    raise ValueError(
                        "Pane layout changed; observe and acquire a fresh token"
                    )
                if method == "mouse":
                    request = self.observation_requests.get(snapshot_id)
                    if not request or request[0] != pane:
                        raise ValueError(
                            "Mouse input requires a current observation snapshot_id"
                        )
                    fresh = await self.observe(pane, ["text"], request[1])
                    if fresh["snapshot_id"] != snapshot_id:
                        raise ValueError("Mouse target snapshot changed; observe again")
                    rect = fresh["region"]
                    if not (
                        rect["x"] <= arguments["x"] < rect["x"] + rect["width"]
                        and rect["y"] <= arguments["y"] < rect["y"] + rect["height"]
                    ):
                        raise ValueError("Mouse target is outside the observed region")
            return await getattr(self, "_" + method)(pane, **arguments)

        def send():
            return asyncio.run(deliver())

        if token is not None:
            geometry = self.control_geometry.get(token)
            pointer = (
                dict(
                    x=arguments.get("x"),
                    y=arguments.get("y"),
                    width=geometry[-2],
                    height=geometry[-1],
                )
                if method == "mouse" and geometry
                else None
            )
            return await asyncio.to_thread(
                store.guarded, pane, self.owner, token, send, pointer
            )
        return await asyncio.to_thread(store.legacy_guarded, pane, send)

    async def send_text(self, pane, text):
        return await self.input_dispatch(pane, "send_text", dict(text=text))

    async def send_keys(self, pane, keys):
        return await self.input_dispatch(pane, "send_keys", dict(keys=keys))

    async def mouse(self, pane, x, y, button="left", action="click"):
        return await self.input_dispatch(
            pane, "mouse", dict(x=x, y=y, button=button, action=action)
        )

    async def control_status(self):
        from cosmos_tui.features.agent.control import ControlStore

        return await asyncio.to_thread(ControlStore(self.backend.argv[2]).status)

    async def acquire_control(self, pane, snapshot_id, task):
        from cosmos_tui.features.agent.control import ControlStore, ControlUnavailable

        if (
            not isinstance(task, str)
            or not 1 <= len(task) <= 120
            or not task.isprintable()
        ):
            raise ValueError("task must be printable text, 1–120 characters")
        request = self.observation_requests.get(snapshot_id)
        if not request or request[0] != pane:
            raise ValueError(
                "Observe the pane with this tool connection before acquiring control"
            )
        current = await self.observe(pane, ["text"], request[1])
        if current["snapshot_id"] != snapshot_id:
            raise ValueError("Snapshot changed; observe again before acquiring control")
        row = await self.pane(pane)
        from cosmos_tui.features.agent.tasks.lifecycle import control_task

        if getattr(self, "conversation", None):
            from cosmos_tui.features.agent.tasks.storage import Tasks

            if Tasks(self.backend.argv[2]).paused(self.conversation):
                raise ControlUnavailable(
                    "paused",
                    "Conversation paused; request explicit user resume confirmation",
                    "context_then_request_resume",
                )
        logical_task = None
        lease = await asyncio.to_thread(
            ControlStore(self.backend.argv[2]).acquire,
            pane,
            self.owner,
            task,
            row["pid"],
            getattr(self, "conversation", None),
            getattr(self, "runtime_id", None),
            logical_task,
        )
        from cosmos_tui.features.agent.headers import synchronize

        try:
            await asyncio.to_thread(synchronize, self.backend.argv)
            observed = await self.observe(pane, ["text"])
            row = await self.pane(pane)

            # Only create/reuse a logical task after ownership and observation
            # succeeded. Serialize association against manual revocation.
            def associate():
                store = ControlStore(self.backend.argv[2])
                with store.locked() as state:
                    store.check(pane)
                    current = state.get(pane)
                    if not current or current["token"] != lease["token"]:
                        raise ValueError("Control revoked before task association")
                    identity = control_task(self.backend.argv[2], self, row, task)
                    current["logical_task"] = identity
                    return identity

            logical_task = await asyncio.to_thread(associate)
        except Exception:
            await asyncio.to_thread(
                ControlStore(self.backend.argv[2]).release,
                pane,
                self.owner,
                lease["token"],
            )
            await asyncio.to_thread(synchronize, self.backend.argv)
            raise
        lease["snapshot_id"] = observed["snapshot_id"]
        lease["dimensions"] = observed["dimensions"]
        old = self.control_tokens.get(pane)
        self.control_geometry.pop(old, None)
        self.control_tokens[pane] = lease["token"]
        self.control_geometry[lease["token"]] = tuple(
            row[k] for k in ("pid", "window_id", "pane_width", "pane_height")
        )
        if logical_task:
            lease["logical_task"] = logical_task
            from cosmos_tui.features.agent.tasks.service import start

            await asyncio.to_thread(start, self.backend.argv[2])
        return lease

    async def release_control(self, pane, token):
        from cosmos_tui.features.agent.control import ControlStore

        # Receipts are connection-local capabilities, bounded independently of
        # live controls. A duplicate close must never close a replacement lease.
        receipts = getattr(self, "_released_controls", None)
        if receipts is None:
            self._released_controls = receipts = {}
        if receipts.get(token) == pane:
            return dict(pane=pane, state="ended", already_finished=True)
        result = await asyncio.to_thread(
            ControlStore(self.backend.argv[2]).release, pane, self.owner, token
        )
        receipts[token] = pane
        if len(receipts) > 128:
            del receipts[next(iter(receipts))]
        from cosmos_tui.features.agent.headers import synchronize

        await asyncio.to_thread(synchronize, self.backend.argv)
        self.control_geometry.pop(token, None)
        if self.control_tokens.get(pane) == token:
            self.control_tokens.pop(pane, None)
        return result

    async def control_input(self, pane, token, kind, arguments, snapshot_id=None):
        allowed = {
            "send_text": {"text"},
            "send_keys": {"keys"},
            "mouse": {"x", "y", "button", "action"},
        }
        if (
            kind not in allowed
            or not isinstance(arguments, dict)
            or set(arguments) - allowed[kind]
            or not {"send_text": {"text"}, "send_keys": {"keys"}, "mouse": {"x", "y"}}[
                kind
            ]
            <= set(arguments)
        ):
            raise ValueError("Invalid controlled input kind or arguments")
        result = await self.input_dispatch(pane, kind, arguments, token, snapshot_id)
        return dict(
            delivery="delivered",
            action_complete=False,
            task_complete=False,
            result=result,
        )

    async def terminal_step(
        self, pane, token, text, submit=False, wait_ms=100, full=False
    ):
        """One literal paste, optional Enter, then a bounded fresh observation."""
        if (
            not isinstance(text, str)
            or len(text) > 32768
            or any(c in text for c in "\n\r\x00")
        ):
            raise ValueError("text must be a single line of at most 32768 characters")
        if (
            type(submit) is not bool
            or type(wait_ms) is not int
            or not 0 <= wait_ms <= 2000
        ):
            raise ValueError("submit must be boolean; wait_ms must be 0–2000")
        if type(full) is not bool:
            raise ValueError("full must be boolean")
        delivered = []
        try:
            if text:
                await self.input_dispatch(pane, "send_text", dict(text=text), token)
                delivered.append("text")
            if submit:
                # Separate guarded delivery lets manual input revoke between stages.
                await self.input_dispatch(
                    pane, "send_keys", dict(keys=["Enter"]), token
                )
                delivered.append("Enter")
            await asyncio.sleep(wait_ms / 1000)
            observation = await self.observe(pane, ["text"])
        except (OSError, RuntimeError, ValueError) as error:
            if not delivered:
                raise
            return dict(
                delivery="partial",
                delivered=delivered,
                error=str(error),
                action_complete=False,
                task_complete=False,
                retry="Observe before retrying; do not repeat delivered input",
            )
        return dict(
            delivery="delivered",
            delivered=delivered,
            observation=self.step_observation(observation, full=full),
            action_complete=False,
            task_complete=False,
        )

    def step_observation(self, observation, *, full=False):
        from cosmos_tui.features.agent.compact import step_observation

        cache = getattr(self, "_step_observations", None)
        if cache is None:
            self._step_observations = cache = {}
        return step_observation(cache, observation, full=full)
