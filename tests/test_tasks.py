"""Tests for tasks.py - get_task_status/get_task_result.

All mocked at the _task_call level (the one function that does real I/O) -
no real network calls needed. These lock in the fix for the bug where a
bare "still pending" response with no reminder led the model to create a
duplicate task even after the wait-timeout message itself was fixed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError
from sv_cli.errors import ConfigError

from sv_mcp.tasks import build_task_tools, get_task_result_handler, get_task_status_handler


@pytest.mark.asyncio
async def test_pending_response_gets_reminder():
    pending = {"task_id": "T1", "status": "pending", "stage": "processing"}
    with patch("sv_mcp.tasks._task_call", return_value=pending):
        result = await get_task_status_handler(task_id="T1", tool="seogpt2")

    assert "_sv_mcp_reminder" in result
    # Still steers away from duplicate paid tasks, stated as a fact rather than an order.
    assert "charged separately" in result["_sv_mcp_reminder"]


@pytest.mark.asyncio
async def test_complete_response_has_no_reminder():
    done = {"task_id": "T2", "status": "complete", "article_html": "<p>done</p>"}
    with patch("sv_mcp.tasks._task_call", return_value=done):
        result = await get_task_result_handler(task_id="T2", tool="seogpt2")

    assert "_sv_mcp_reminder" not in result


@pytest.mark.asyncio
async def test_error_response_has_no_reminder():
    errored = {"task_id": "T3", "status": "error", "message": "generation failed"}
    with patch("sv_mcp.tasks._task_call", return_value=errored):
        result = await get_task_status_handler(task_id="T3", tool="seogpt2")

    assert "_sv_mcp_reminder" not in result


@pytest.mark.asyncio
async def test_unknown_task_id_error_mentions_mcp_tool_param_not_cli_flag():
    with patch(
        "sv_mcp.tasks._task_call",
        side_effect=ConfigError('No local tool mapping found for task "bogus".'),
    ):
        with pytest.raises(ToolError) as exc_info:
            await get_task_status_handler(task_id="bogus")

    message = str(exc_info.value)
    assert "--tool" not in message
    assert '"tool"' in message


@pytest.mark.asyncio
async def test_other_cli_errors_pass_through_as_tool_error():
    with patch("sv_mcp.tasks._task_call", side_effect=ConfigError("something else broke")):
        with pytest.raises(ToolError, match="something else broke"):
            await get_task_status_handler(task_id="T4")


def test_task_call_resolves_api_key_via_oauth_claims_not_just_env_var():
    """Regression test: tasks.py's own key resolution was never updated for
    http/OAuth mode - it only ever checked SV_API_KEY, so get_task_status/
    get_task_result always failed with "missing API key" in http mode even
    though task creation (execution.py's separate, correctly-fixed
    resolution) worked fine. _resolve_api_key() must be consulted here too."""
    from sv_mcp.tasks import _task_call

    fake_definitions = MagicMock()
    fake_definitions.resolve_tool.return_value = "geogptaudit"
    fake_definitions.get_tool.return_value = {"endpoint": "https://api.example/geogptaudit"}

    fake_api_client = MagicMock()
    fake_api_client.request_tool.return_value.data = {"task_id": "T1", "status": "complete"}

    with patch("sv_mcp.tasks.DefinitionsManager", return_value=fake_definitions), patch(
        "sv_mcp.tasks.get_task_tool", return_value="geogptaudit"
    ), patch("sv_mcp.tasks._resolve_api_key", return_value="000010oauth-resolved-key"), patch(
        "sv_mcp.tasks.APIClient", return_value=fake_api_client
    ):
        _task_call("T1", "status", "geogptaudit")

    _, kwargs = fake_api_client.request_tool.call_args
    assert kwargs["api_key"] == "000010oauth-resolved-key"


def test_build_task_tools_returns_both_tools_with_correct_names():
    tools = build_task_tools()
    names = {t.name for t in tools}
    assert names == {"get_task_status", "get_task_result"}
    for tool in tools:
        assert tool.parameters["required"] == ["task_id"]
        assert "task_id" in tool.parameters["properties"]
        assert "tool" in tool.parameters["properties"]
