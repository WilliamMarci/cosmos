"""Authenticated runtime conversation identity; never a model tool argument."""

import hashlib
import hmac
import os


def scoped_tools(tools, arguments):
    arguments = dict(arguments)
    context = arguments.pop("_cosmos_context", None)
    if context is None:
        return tools, arguments  # Unpatched/system agents retain per-call permissions.
    key = os.environ.get("COSMOS_AGENT_CONTEXT_KEY", "")
    if not key or not isinstance(context, dict):
        raise ValueError("Unauthenticated Agent conversation")
    session, signature = context.get("session"), context.get("signature")
    if (
        not isinstance(session, str)
        or not 1 <= len(session) <= 256
        or not isinstance(signature, str)
    ):
        raise ValueError("Invalid Agent conversation")
    expected = hmac.new(key.encode(), session.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise PermissionError("Unauthenticated Agent conversation")
    if not hasattr(tools, "_conversations"):
        tools._conversations = {}
    if session not in tools._conversations:
        tools._conversations[session] = type(tools)(tools.backend.argv[2])
    scoped = tools._conversations[session]
    scoped.binding = tools.binding
    scoped.conversation = session
    scoped.runtime_id = hashlib.sha256(key.encode()).hexdigest()[:24]
    return scoped, arguments
