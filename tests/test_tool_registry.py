"""Tests for tool_registry.build_tools() and friends.

build_tools() normally pulls definitions through a real DefinitionsManager
(network/cache-backed) - these tests substitute a small fake with the same
`.get_tool(canonical)` interface, backed by the frozen fixture snapshot, so
the whole suite stays offline.
"""

from __future__ import annotations

from sv_cli.adapters import TOOL_ADAPTERS

from sv_mcp.execution import DEFAULT_WAIT_TIMEOUT_SECONDS
from sv_mcp.tool_registry import (
    MCP_EXCLUDED_TOOLS,
    MCP_NAME_OVERRIDES,
    TOOL_DESCRIPTIONS,
    _description_for,
    _mcp_name_for,
    build_tools,
)


class _FakeDefinitionsManager:
    def __init__(self, definitions: dict) -> None:
        self._definitions = definitions

    def get_tool(self, canonical: str) -> dict:
        return {"definition": self._definitions[canonical]}


# Adapters SV MCP actually exposes - every sv_cli tool family except MCP_EXCLUDED_TOOLS.
EXPOSED_ADAPTERS = {k: a for k, a in TOOL_ADAPTERS.items() if k not in MCP_EXCLUDED_TOOLS}


def test_build_tools_returns_every_exposed_tool_family(definitions):
    tools = build_tools(_FakeDefinitionsManager(definitions))
    names = {t.name for t in tools}
    # MCP-facing names, not canonicals - see MCP_NAME_OVERRIDES (e.g. seogpt2 -> prose).
    assert names == {_mcp_name_for(a) for a in EXPOSED_ADAPTERS.values()}
    # 16 sv_cli tool families minus seo-image. The two task tools are added separately
    # (tasks.py), for 17 MCP tools in total.
    assert len(tools) == 15


def test_seo_image_is_not_exposed(definitions):
    """Anthropic's Software Directory Policy (4B) does not accept standalone AI image
    generation, so seo-image stays in the API/CLI but is never registered as an MCP tool."""
    names = {t.name for t in build_tools(_FakeDefinitionsManager(definitions))}
    assert "seo-image" in TOOL_ADAPTERS
    assert "seo-image" not in names


def test_async_tools_get_wait_parameter(definitions):
    tools = {t.name: t for t in build_tools(_FakeDefinitionsManager(definitions))}
    for canonical, adapter in EXPOSED_ADAPTERS.items():
        if adapter.async_likely:
            name = _mcp_name_for(adapter)
            assert "wait" in tools[name].parameters["properties"], f"{canonical} missing wait param"
            assert tools[name].parameters["properties"]["wait"]["type"] == "boolean"


def test_sync_tools_do_not_get_wait_parameter(definitions):
    tools = {t.name: t for t in build_tools(_FakeDefinitionsManager(definitions))}
    for canonical, adapter in EXPOSED_ADAPTERS.items():
        if not adapter.async_likely:
            name = _mcp_name_for(adapter)
            assert "wait" not in tools[name].parameters["properties"], f"{canonical} unexpectedly has wait"


def test_async_tools_only_expose_default_action(definitions):
    # geogptaudit/seogpt2/seogptcompare/seogptmapping all have create-task/get-task-status/
    # get-result/raw in their real adapter - the MCP-facing creation tool should only ever
    # advertise create-task, since status/result are handled by the dedicated task tools.
    tools = {t.name: t for t in build_tools(_FakeDefinitionsManager(definitions))}
    for canonical, adapter in EXPOSED_ADAPTERS.items():
        if adapter.async_likely:
            assert "action" not in tools[_mcp_name_for(adapter)].parameters["properties"]


def test_seogpt2_is_exposed_to_the_model_as_prose(definitions):
    """MCP gets a straight rename, not a dual listing.

    The CLI keeps "seogpt2" working as an alias (scripts may hardcode it), but an
    MCP client rediscovers tool names on every connect, so listing both would just
    hand the model two identical tools to choose between.
    """
    names = {t.name for t in build_tools(_FakeDefinitionsManager(definitions))}
    assert "prose" in names
    assert "seogpt2" not in names
    # Overrides are keyed by canonical, which sv_cli deliberately leaves as seogpt2.
    assert MCP_NAME_OVERRIDES["seogpt2"] == "prose"
    assert TOOL_ADAPTERS["seogpt2"].canonical == "seogpt2"


def test_every_tool_adapter_has_a_real_description():
    """Tripwire: if sv_cli adds a new tool without us writing a description for it,
    this fails loudly instead of silently shipping the generic fallback text."""
    for canonical in EXPOSED_ADAPTERS:
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


# Anthropic Software Directory Policy, section 2: descriptions say what a tool does and when
# to use it - no instructions pushing the model to prefer the tool, no marketing language.
_BANNED_PHRASES = [
    r"\bIMPORTANT\b", r"always call", r"prefer this", r"yourself", r"instead of calling",
    r"whenever the user", r"never call", r"\bdo not\b", r"\bdon'?t\b", r"you could",
    r"\bbest\b", r"#1", r"powerful", r"publish-ready", r"\breal\b",
]


def _all_description_text(definitions) -> dict[str, str]:
    from sv_mcp.tasks import build_task_tools

    texts = {}
    for tool in build_tools(_FakeDefinitionsManager(definitions)) + build_task_tools():
        texts[tool.name] = tool.description
        for prop_name, prop in tool.parameters.get("properties", {}).items():
            if prop_name in ("wait", "task_id", "tool") and isinstance(prop.get("description"), str):
                texts[f"{tool.name}.{prop_name}"] = prop["description"]
    return texts


def test_descriptions_contain_no_model_directed_instructions(definitions):
    import re

    offenders = []
    for where, text in _all_description_text(definitions).items():
        for phrase in _BANNED_PHRASES:
            if re.search(phrase, text, re.IGNORECASE):
                offenders.append(f"{where}: {phrase}")
    assert not offenders, "Descriptions violate policy section 2:\n" + "\n".join(offenders)


# --- Titles + annotations: Anthropic Software Directory Policy 5E -----------------------------

EXPECTED_READ_ONLY = {
    "better-keywords", "content-quality", "content-transformer", "core-analysis", "insight-igniter",
    "ranklens", "seogpt", "topical-authority", "top-competitors", "marketplace-services",
    "get_task_status", "get_task_result",
}
# Each of these saves a task or record to the user's SV account (see annotations.py).
EXPECTED_NOT_READ_ONLY = {"prose", "geogptaudit", "seogptcompare", "seogptmapping", "preliminaryaudit"}


def _all_tools(definitions):
    from sv_mcp.tasks import build_task_tools

    return build_tools(_FakeDefinitionsManager(definitions)) + build_task_tools()


def test_every_tool_has_title_and_required_annotations(definitions):
    for tool in _all_tools(definitions):
        a = tool.annotations
        assert tool.title, f"{tool.name}: missing title"
        assert a is not None and a.title == tool.title, f"{tool.name}: annotation title missing/mismatched"
        assert a.readOnlyHint is not None, f"{tool.name}: missing readOnlyHint"
        assert a.destructiveHint is False, f"{tool.name}: no SV tool deletes or overwrites user data"
        assert len(tool.name) <= 64, f"{tool.name}: name over the 64-char limit (policy 5C)"


def test_read_only_classification_matches_real_behavior(definitions):
    tools = {t.name: t for t in _all_tools(definitions)}
    assert set(tools) == EXPECTED_READ_ONLY | EXPECTED_NOT_READ_ONLY  # 17 tools, nothing unclassified
    for name in EXPECTED_READ_ONLY:
        assert tools[name].annotations.readOnlyHint is True, name
    for name in EXPECTED_NOT_READ_ONLY:
        assert tools[name].annotations.readOnlyHint is False, name


def test_every_exposed_tool_has_hand_written_meta():
    """Tripwire, like the description one: a new sv_cli tool must get a title and a
    read-only decision here before it ships."""
    from sv_mcp.annotations import TOOL_META

    for canonical in EXPOSED_ADAPTERS:
        assert canonical in TOOL_META, f"{canonical} has no TOOL_META entry in sv_mcp/annotations.py"


def test_unknown_tool_defaults_to_not_read_only():
    from sv_mcp.annotations import annotations_for

    title, annotations = annotations_for("brand-new-tool", "brand-new-tool")
    assert title == "brand-new-tool"
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
