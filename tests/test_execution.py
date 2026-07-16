"""Tests for execution.call_sv_tool() - the async wrapper around sv_cli.executor.execute_tool().

All mocked - no real network calls, no SV_API_KEY needed. These lock in the
two most consequential bug fixes from this session: a wait timeout must
return successfully (not raise), and a CLIError must become a clean ToolError.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError
from sv_cli.errors import CLIError
from sv_cli.errors import TimeoutError as SVTimeoutError

from sv_mcp.execution import call_sv_tool


@pytest.mark.asyncio
async def test_cli_error_becomes_tool_error():
    with patch("sv_mcp.execution.execute_tool", side_effect=CLIError("bad request")):
        with pytest.raises(ToolError, match="bad request"):
            await call_sv_tool("seogpt", "generate", {"kw": "test"})


@pytest.mark.asyncio
async def test_wait_timeout_returns_success_not_error():
    task_id = "abc123"
    timeout_message = (
        f"The task is still running.\nTask ID:\n{task_id}\nCheck later with:\nsv task status {task_id}"
    )
    with patch("sv_mcp.execution.execute_tool", side_effect=SVTimeoutError(timeout_message)):
        result = await call_sv_tool("seogpt2", "create-task", {"Topic": "test"}, wait=True, wait_timeout=45)

    assert result["status"] == "still_running"
    assert result["task_id"] == task_id
    assert "get_task_status" in result["message"]
    assert "get_task_result" in result["message"]


@pytest.mark.asyncio
async def test_wait_timeout_message_without_task_id_still_returns_cleanly():
    with patch("sv_mcp.execution.execute_tool", side_effect=SVTimeoutError("no task id in this message")):
        result = await call_sv_tool("seogpt2", "create-task", {"Topic": "test"}, wait=True)

    assert result["status"] == "still_running"
    assert result["task_id"] is None


@pytest.mark.asyncio
async def test_wait_true_passes_wait_options_through():
    captured = {}

    def fake_execute_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    with patch("sv_mcp.execution.execute_tool", side_effect=fake_execute_tool):
        await call_sv_tool("geogptaudit", "create-task", {}, wait=True, wait_timeout=45)

    assert captured["wait_options"] is not None
    assert captured["wait_options"].wait is True
    assert captured["wait_options"].timeout == 45


@pytest.mark.asyncio
async def test_wait_false_means_no_wait_options():
    captured = {}

    def fake_execute_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    with patch("sv_mcp.execution.execute_tool", side_effect=fake_execute_tool):
        await call_sv_tool("geogptaudit", "create-task", {}, wait=False)

    assert captured["wait_options"] is None


@pytest.mark.asyncio
async def test_api_key_read_from_environment(monkeypatch):
    monkeypatch.setenv("SV_API_KEY", "test-key-123")
    captured = {}

    def fake_execute_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    with patch("sv_mcp.execution.execute_tool", side_effect=fake_execute_tool):
        await call_sv_tool("better-keywords", "research", {"kw": "test"})

    assert captured["runtime"].api_key == "test-key-123"
    assert captured["runtime"].quiet is True
    assert captured["runtime"].strict is True
