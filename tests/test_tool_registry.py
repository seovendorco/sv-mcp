"""Tests for tool_registry.build_tools() and friends.

build_tools() normally pulls definitions through a real DefinitionsManager
(network/cache-backed) - these tests substitute a small fake with the same
`.get_tool(canonical)` interface, backed by the frozen fixture snapshot, so
the whole suite stays offline.
"""

from __future__ import annotations

from sv_cli.adapters import TOOL_ADAPTERS

from sv_mcp.execution import DEFAULT_WAIT_TIMEOUT_SECONDS
from sv_mcp.tool_registry import TOOL_DESCRIPTIONS, _description_for, build_tools


class _FakeDefinitionsManager:
    def __init__(self, definitions: dict) -> None:
        self._definitions = definitions

    def get_tool(self, canonical: str) -> dict:
        return {"definition": self._definitions[canonical]}


def test_build_tools_returns_all_16_tool_families(definitions):
    tools = build_tools(_FakeDefinitionsManager(definitions))
    names = {t.name for t in tools}
    assert names == set(TOOL_ADAPTERS.keys())
    assert len(tools) == 16


def test_async_tools_get_wait_parameter(definitions):
    tools = {t.name: t for t in build_tools(_FakeDefinitionsManager(definitions))}
    for canonical, adapter in TOOL_ADAPTERS.items():
        if adapter.async_likely:
            assert "wait" in tools[canonical].parameters["properties"], f"{canonical} missing wait param"
            assert tools[canonical].parameters["properties"]["wait"]["type"] == "boolean"


def test_sync_tools_do_not_get_wait_parameter(definitions):
    tools = {t.name: t for t in build_tools(_FakeDefinitionsManager(definitions))}
    for canonical, adapter in TOOL_ADAPTERS.items():
        if not adapter.async_likely:
            assert "wait" not in tools[canonical].parameters["properties"], f"{canonical} unexpectedly has wait"


def test_async_tools_only_expose_default_action(definitions):
    # geogptaudit/seogpt2/seogptcompare/seogptmapping all have create-task/get-task-status/
    # get-result/raw in their real adapter - the MCP-facing creation tool should only ever
    # advertise create-task, since status/result are handled by the dedicated task tools.
    tools = {t.name: t for t in build_tools(_FakeDefinitionsManager(definitions))}
    for canonical, adapter in TOOL_ADAPTERS.items():
        if adapter.async_likely:
            assert "action" not in tools[canonical].parameters["properties"]


def test_every_tool_adapter_has_a_real_description():
    """Tripwire: if sv_cli adds a new tool without us writing a description for it,
    this fails loudly instead of silently shipping the generic fallback text."""
    for canonical in TOOL_ADAPTERS:
        assert canonical in TOOL_DESCRIPTIONS, (
            f"{canonical} has no hand-written TOOL_DESCRIPTIONS entry - "
            "add one to sv_mcp/tool_registry.py before shipping"
        )


def test_missing_description_falls_back_gracefully():
    from sv_cli.adapters import ToolAdapter

    fake_adapter = ToolAdapter(canonical="not-a-real-tool", command="not-a-real-tool", default_action="run")
    description = _description_for(fake_adapter)
    assert "not-a-real-tool" in description
    assert "No hand-written description" in description


def test_wait_default_timeout_is_45_seconds():
    # Regression guard for the specific bug this value fixes (see execution.py's comment) -
    # if this creeps back up toward 120s, the duplicate-task bug it fixed can resurface.
    assert DEFAULT_WAIT_TIMEOUT_SECONDS == 45
