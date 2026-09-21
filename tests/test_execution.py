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


# --- readable_error: policy 5A - helpful errors instead of raw JSON --------------------------

def _api_error(code, message, field="", details=None, status=400):
    from sv_cli.errors import APIError

    data = {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "field": field, "details": details or []},
    }
    return APIError(f"API request failed: HTTP {status}. {{raw json}}", status_code=status, data=data)


def test_readable_error_uses_api_message_not_raw_json():
    from sv_mcp.execution import readable_error

    text = readable_error(_api_error("VALIDATION_ERROR", "Topic mode must be seo or geo.", field="topicmode"))
    assert text.startswith("Topic mode must be seo or geo.")
    assert "'topicmode'" in text
    assert "VALIDATION_ERROR" in text
    assert "{raw json}" not in text


def test_readable_error_explains_insufficient_points():
    from sv_mcp.execution import readable_error

    err = _api_error(
        "INSUFFICIENT_POINTS",
        "Sorry, there are not enough points available to make this API call.",
        field="points",
        details={"required_points": 10, "available_points": 0},
        status=402,
    )
    text = readable_error(err)
    assert "Required: 10 points, available: 0." in text
    assert "Add points" in text


def test_readable_error_falls_back_to_message_without_structured_data():
    from sv_cli.errors import APIError, NetworkError
    from sv_mcp.execution import readable_error

    # Older sv_cli (no exc.data) and non-API errors keep their own text unchanged.
    assert readable_error(APIError("API request failed: HTTP 500. oops")) == "API request failed: HTTP 500. oops"
    assert readable_error(NetworkError("Network error while calling SV API: boom")) == (
        "Network error while calling SV API: boom"
    )
