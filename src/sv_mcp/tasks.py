"""Granular task-status/result MCP tools.

Mirrors sv_cli.main's `sv task status` / `sv task result` CLI commands
(main.py's task_call()) exactly: one direct API call each, no polling
loop. sv_cli.tasks.wait_for_task()'s poll loop is only used by the
blocking "wait=True" convenience path inside each async tool's own
handler (see tool_registry.py) - these two tools are the manual,
non-blocking follow-up path instead.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool
from sv_cli.api_client import APIClient
from sv_cli.config import resolve_api_key
from sv_cli.definitions import DefinitionsManager
from sv_cli.errors import CLIError
from sv_cli.tasks import DONE_STATES, ERROR_STATES, extract_status, get_task_tool, result_payload, status_payload

TASK_ID_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "The task_id returned when the task was created."},
        "tool": {
            "type": "string",
            "description": (
                "Which tool created the task (e.g. 'geogptaudit'). Only needed if the task_id "
                "wasn't created in this same session, since sv_cli otherwise remembers it locally."
            ),
        },
    },
    "required": ["task_id"],
    "additionalProperties": False,
}


def _task_call(task_id: str, action: str, tool: str | None) -> Any:
    definitions = DefinitionsManager()
    canonical = definitions.resolve_tool(get_task_tool(task_id, tool))
    entry = definitions.get_tool(canonical)
    endpoint = entry.get("endpoint")
    api_key = resolve_api_key(
        cli_api_key=os.environ.get("SV_API_KEY"),
        allow_prompt=False,
        non_interactive=True,
    )
    payload = status_payload(task_id) if action == "status" else result_payload(task_id)
    return APIClient().request_tool(endpoint=str(endpoint), payload=payload, api_key=api_key).data


async def _run_task_call(task_id: str, action: str, tool: str | None) -> Any:
    try:
        data = await asyncio.to_thread(_task_call, task_id, action, tool)
    except CLIError as exc:
        # get_task_tool()'s own message says "re-run with --tool" - a CLI flag, not something
        # the model can do. Same class of issue as execution.py's TimeoutError rewrite.
        if "No local tool mapping found" in str(exc):
            raise ToolError(
                f'No local record of which tool created task "{task_id}" (this can happen if the '
                "task wasn't created in this session). Retry with the tool name, e.g. "
                f'{{"task_id": "{task_id}", "tool": "seogpt2"}}.'
            ) from exc
        raise ToolError(str(exc)) from exc

    # Reinforce this on every single poll, not just the first wait=True timeout: a bare
    # "not ready yet" with no reminder, repeated over many polls across a long-running task,
    # turned out in practice to still lead the model to create a duplicate task instead of
    # keeping to this task_id (see plan.md's Phase 2 status - this recurred even after the
    # wait-timeout message itself was fixed).
    status = extract_status(data)
    if status not in DONE_STATES and status not in ERROR_STATES and isinstance(data, dict):
        data = {
            **data,
            "_sv_mcp_reminder": (
                f'Task "{task_id}" is still in progress (this is expected, not an error). Do not '
                "create a new task for the same request - it will be charged separately and won't "
                "finish any faster. Check again in a bit with the same task_id."
            ),
        }
    return data


async def get_task_status_handler(**kwargs: Any) -> Any:
    return await _run_task_call(kwargs["task_id"], "status", kwargs.get("tool"))


async def get_task_result_handler(**kwargs: Any) -> Any:
    return await _run_task_call(kwargs["task_id"], "result", kwargs.get("tool"))


def build_task_tools() -> list[FunctionTool]:
    return [
        FunctionTool(
            fn=get_task_status_handler,
            name="get_task_status",
            description="Check the status of an async SV task by task_id.",
            parameters=TASK_ID_SCHEMA,
        ),
        FunctionTool(
            fn=get_task_result_handler,
            name="get_task_result",
            description="Fetch the result of an async SV task by task_id, once it has finished.",
            parameters=TASK_ID_SCHEMA,
        ),
    ]
