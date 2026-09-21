"""Async wrapper around sv_cli.executor.execute_tool()."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from sv_cli.errors import CLIError
from sv_cli.errors import TimeoutError as SVTimeoutError
from sv_cli.executor import RuntimeOptions, WaitOptions, execute_tool

DEFAULT_WAIT_TIMEOUT_SECONDS = 45
# Deliberately well under a minute: two separate real tests (seogpt2, seogptcompare) both
# produced a duplicate task ~66-69s after the first call, on different days - consistent with
# Claude Desktop's own MCP client having a tool-call timeout somewhere around a minute, shorter
# than this server's old 120s internal wait. If that theory is right, the fix is for this
# server's own "still running" response to reach the client before that outside ceiling does,
# not to make the message at 120s more convincing - by then it's already too late.

_TASK_ID_FROM_TIMEOUT_MESSAGE = re.compile(r"Task ID:\n(\S+)")

# Extra guidance appended to specific SV API error codes, so the user gets something they can
# act on rather than just a code (Anthropic Software Directory Policy 5A).
_ERROR_HINTS: dict[str, str] = {
    "AUTH_INVALID": "Reconnect the SV connector and sign in again.",
    "AUTH_MISSING": "Reconnect the SV connector and sign in again.",
    "AUTH_CHECK_FAILED": "The SV sign-in service could not be reached. Try again shortly.",
    "INSUFFICIENT_POINTS": "Add points to the SV account, then try again.",
    "UPSTREAM_TIMEOUT": "The SV service took too long to respond. Try again shortly.",
    "UPSTREAM_UNAVAILABLE": "The SV service is temporarily unavailable. Try again shortly.",
    "UPSTREAM_ERROR": "The SV service could not complete this request. Try again, or adjust the inputs.",
    "UPSTREAM_EMPTY_RESPONSE": "The SV service returned no result for this request. Try again, or adjust the inputs.",
    # Reached only after sv_cli's own automatic retries, i.e. several calls were competing.
    "RATE_LIMITED": "Several calls were made at the same time. Try this one again in a few seconds.",
}


def readable_error(exc: CLIError) -> str:
    """A user-actionable message for a failed SV call.

    sv_cli's APIError message embeds the API's whole JSON error envelope, which is fine for a
    terminal but reads badly as a tool error. When the structured response is available
    (sv_cli attaches it as exc.data), use the API's own message, field and code instead. Any
    other error - network, timeout, or an older sv_cli without exc.data - keeps its text.
    """
    data = getattr(exc, "data", None)
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict) or not error.get("message"):
        return str(exc)

    parts = [str(error["message"]).rstrip(".") + "."]
    code = error.get("code")
    details = error.get("details")
    if code == "INSUFFICIENT_POINTS" and isinstance(details, dict):
        parts.append(
            f"Required: {details.get('required_points')} points, "
            f"available: {details.get('available_points')}."
        )
    elif error.get("field") and code == "VALIDATION_ERROR":
        parts.append(f"Check the '{error['field']}' input.")
    if code in _ERROR_HINTS:
        parts.append(_ERROR_HINTS[code])
    if code:
        parts.append(f"(SV error code: {code})")
    return " ".join(parts)


def _resolve_api_key() -> str | None:
    """The SV API key to use for this specific call.

    stdio mode (local, single-user): no auth is configured on the
    server at all, so get_access_token() returns None (confirmed from its
    source - it cleanly falls through every lookup path rather than raising
    when there's no HTTP request/auth context). Falls back to the SV_API_KEY
    environment variable, unchanged behavior.

    http mode (hosted, multi-user): FastMCP already rejected any
    request without a valid token before this code ever runs (auth is
    required via server.py's auth=OAuthProxy(...)), so a real, validated
    AccessToken is always available here. Its .claims come from
    IntrospectionTokenVerifier, which populates them from SEOB's
    checktoken.php response - including the custom "api_key" field
    checktoken.php adds alongside the standard RFC 7662 fields.
    """
    access_token = get_access_token()
    if access_token is not None:
        claimed_key = access_token.claims.get("api_key")
        if claimed_key:
            return claimed_key
    return os.environ.get("SV_API_KEY")


async def call_sv_tool(
    tool_name: str,
    action: str | None,
    params: dict[str, Any],
    *,
    wait: bool = False,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> Any:
    runtime = RuntimeOptions(
        api_key=_resolve_api_key(),
        output_format="json",
        quiet=True,  # execute_tool prints to stdout by default, which would corrupt stdio JSON-RPC
        strict=True,  # inputSchema already bakes in valid enum values; no fuzzy matching needed
        no_fuzzy=True,
        non_interactive=True,  # MCP has no terminal to prompt into
    )
    wait_options = (
        WaitOptions(wait=True, timeout=wait_timeout, poll_interval=5, no_progress=True) if wait else None
    )
    try:
        return await asyncio.to_thread(  # execute_tool is synchronous and can block on wait_for_task
            execute_tool,
            tool_name=tool_name,
            action=action,
            params=params,
            runtime=runtime,
            wait_options=wait_options,
            client_type="mcp",
        )
    except SVTimeoutError as exc:
        # A wait timeout is NOT a failure - the task was created fine and is still running, only
        # the "wait for it" convenience part ran out of patience. Raising here would be wrong: an
        # errored tool call reads to the model as "something broke, maybe retry" - which creates a
        # second, duplicate (paid) task for the same prompt instead of following up on the first.
        # So this returns a normal, successful result carrying the task_id, exactly like wait=False
        # would have, rather than raising.
        match = _TASK_ID_FROM_TIMEOUT_MESSAGE.search(str(exc))
        task_id = match.group(1) if match else None
        return {
            "status": "still_running",
            "task_id": task_id,
            "message": (
                f"Still running after {wait_timeout}s - this is normal, not an error. Starting "
                f"another task for the same request would be charged separately and would not "
                f'finish sooner. Check on this one with get_task_status(task_id="{task_id}") or '
                f'get_task_result(task_id="{task_id}").'
            ),
        }
    except CLIError as exc:
        raise ToolError(readable_error(exc)) from exc
