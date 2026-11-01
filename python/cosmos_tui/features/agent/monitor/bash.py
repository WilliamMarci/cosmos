"""Bash prompt sequence emitted by cosmosrc; no screen heuristics."""

import re


async def prompt_stamp(tools, pane):
    value = (
        await tools.backend.cli(
            "show-options", "-p", "-qv", "-t", pane, "@cosmos_prompt_stamp"
        )
    ).strip()
    return value if re.fullmatch(r"[0-9]+:[0-9]+", value) else None
