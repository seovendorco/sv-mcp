"""Builds MCP FunctionTool objects from sv_cli's live tool definitions.

Registers every family in sv_cli.adapters.TOOL_ADAPTERS (minus
MCP_EXCLUDED_TOOLS), partitioned into the sync and async paths by each adapter's
async_likely flag - not a hand-picked list anymore. A new tool added to sv_cli's
adapters.py appears here automatically on next restart, picking up
TOOL_DESCRIPTIONS' fallback text until someone writes it a real one.
"""

from __future__ import annotations

from typing import Any

from fastmcp.tools import FunctionTool
from sv_cli.adapters import TOOL_ADAPTERS, ToolAdapter
from sv_cli.definitions import DefinitionsManager

from .annotations import annotations_for
from .execution import DEFAULT_WAIT_TIMEOUT_SECONDS, call_sv_tool
from .schemas import build_input_schema

# Hand-authored, not pulled from the API: sv_cli's tool definitions only carry
# per-field descriptions, no tool-level summary. Grounded in each tool's real
# api_output schema (what it actually returns), not guessed from the tool name.
#
# Written to Anthropic's Software Directory Policy, section 2: each description
# says what the tool does and when to use it, in plain factual terms. No
# instructions that push the model to prefer the tool ("always call this",
# "don't do it yourself"), and no marketing language. Cross-references between
# SV tools are fine where they stop similar tools being confused (policy 2C).
# tests/test_tool_registry.py enforces the banned phrases.
TOOL_DESCRIPTIONS: dict[str, str] = {
    "better-keywords": (
        "Keyword research for a seed keyword. The 'research' action returns related keyword "
        "variants with monthly search volume, CPC, competition score and search intent. The "
        "'filter' action filters a keyword list supplied in the request. Use when the user asks "
        "for keyword research or keyword ideas."
    ),
    "content-quality": (
        "Scores a live page's content quality (E-E-A-T and helpful-content criteria) for a target "
        "keyword. Returns up to 15 scored criteria per URL (0-100 each, with reasoning). Pass url_b "
        "to compare two pages. Use when the user asks to evaluate the content quality of a page."
    ),
    "content-transformer": (
        "Rewrites or reformats text supplied by the user into a chosen content type (for example a "
        "meta title, product description or landing-page copy), applying SEO rules for keyword "
        "placement, length and tone. Returns the rewritten text. Use when the user asks to rewrite, "
        "repurpose or reformat existing text. To write new content from scratch, use seogpt "
        "(short-form) or prose (long-form)."
    ),
    "core-analysis": (
        "Analyzes a URL's on-page SEO: HTTP status, load speed, title tag, meta description, H1 and "
        "H2 headings, and keyword usage. Use for an element-by-element review of one page. For a "
        "single overall health score, use preliminaryaudit."
    ),
    "insight-igniter": (
        "Shows which entities and topics AI engines associate with a website, given only its URL. "
        "Returns one result set per AI engine queried. Synchronous and fast. Use for open-ended "
        "questions such as 'what does AI associate with this site?'. To score visibility for "
        "specific entities or keywords the user already has, use geogptaudit (slower, asynchronous)."
    ),
    "preliminaryaudit": (
        "Runs a quick automated SEO health check of a URL (canonical tags, blocking meta tags, load "
        "speed and similar checks) and returns an overall score out of a maximum. Use for a fast "
        "health check. For an element-by-element breakdown, use core-analysis."
    ),
    "ranklens": (
        "Measures how a website ranks for an entity or keyword across repeated AI-engine queries. "
        "The 'rank' action returns one ranking data point per sample. The 'competitors' action takes "
        "the mgptid from a rank result and returns the competitors that appeared in those samples. "
        "Pass brand when the site's brand name cannot be worked out from its domain."
    ),
    "seogpt": (
        "Generates short-form SEO text such as meta titles, meta descriptions or short product "
        "descriptions, and returns it directly (synchronous). Can return several variations at once "
        "via qty. Use when the user asks for short SEO copy. For full articles or blog posts, use "
        "prose."
    ),
    "topical-authority": (
        "Builds a topical content plan for a keyword: a list of suggested article topics, plus "
        "related subtopic ideas in seo mode. Use for content strategy and planning. To write the "
        "articles themselves, use prose."
    ),
    "top-competitors": (
        "Lists the top-ranking competitor URLs for a keyword. Use for a quick competitor list. For a "
        "full comparison of a specific URL against its competitors, use seogptcompare."
    ),
    "marketplace-services": (
        "Searches SV's catalog of purchasable services (SEO, PPC, development and others) by search "
        "term, with optional price, series and category filters. Returns matching services with "
        "prices and links. Use only when the user asks to find SV services."
    ),
    "geogptaudit": (
        "Scores how visible a domain or page is in AI-generated answers (such as ChatGPT, Gemini and "
        "Google AI Overviews) for entities or keywords the user specifies. Asynchronous and usually "
        "takes several minutes: returns a task_id immediately unless wait is true. Use when the user "
        "asks for a GEO audit or an AI-visibility score for specific entities. For open-ended "
        "questions about what AI associates with a site, use insight-igniter."
    ),
    # Keyed by canonical ("seogpt2"), while the tool is exposed to the model as
    # "prose" - see MCP_NAME_OVERRIDES below.
    "seogpt2": (
        "Prose, SV's long-form writing agent: writes a full article or blog post on a topic and "
        "returns the finished text. Asynchronous and usually takes several minutes: returns a "
        "task_id immediately unless wait is true. Use when the user asks for a long-form article. "
        "For short snippets such as meta titles, use seogpt."
    ),
    "seogptcompare": (
        "Compares a target URL against its top competitors for a keyword and returns a competitive "
        "SEO analysis. Asynchronous: returns a task_id immediately unless wait is true."
    ),
    "seogptmapping": (
        "Maps a list of keywords to the most relevant existing pages on a target domain, for "
        "internal linking or content-gap planning. Asynchronous: returns a task_id immediately "
        "unless wait is true."
    ),
}


# MCP tool names are what the model sees in its tool list, and clients fetch that
# list fresh on every connect - nothing references them persistently the way a shell
# script can hardcode a CLI command. So unlike the CLI (which keeps "seogpt2" working
# as an alias so existing scripts don't break), MCP gets a straight rename: listing
# both names would just show the model two identical tools to pick between.
#
# Keyed by canonical, so this stays correct while sv_cli's canonical remains "seogpt2".
MCP_NAME_OVERRIDES: dict[str, str] = {
    "seogpt2": "prose",
}

# Tools the SV API and CLI support but SV MCP deliberately does not expose.
# seo-image: Anthropic's Software Directory Policy (section 4B) does not accept
# software that uses AI to generate images as a standalone service. It stays
# available through the API and CLI.
MCP_EXCLUDED_TOOLS: frozenset[str] = frozenset({"seo-image"})


def _mcp_name_for(adapter: ToolAdapter) -> str:
    return MCP_NAME_OVERRIDES.get(adapter.canonical, adapter.canonical)


def _description_for(adapter: ToolAdapter) -> str:
    return TOOL_DESCRIPTIONS.get(
        adapter.canonical,
        f"SV '{adapter.command}' tool ({adapter.default_action}). "
        "No hand-written description yet for this tool - see sv_mcp/tool_registry.py.",
    )


def _make_sync_handler(canonical: str, default_action: str):
    async def handler(**kwargs: Any) -> Any:
        action = kwargs.pop("action", None) or default_action
        return await call_sv_tool(canonical, action, kwargs)

    handler.__name__ = f"{canonical.replace('-', '_')}_handler"
    return handler


def _make_async_handler(canonical: str, default_action: str):
    async def handler(**kwargs: Any) -> Any:
        wait = kwargs.pop("wait", False)
        return await call_sv_tool(
            canonical,
            default_action,
            kwargs,
            wait=wait,
            wait_timeout=DEFAULT_WAIT_TIMEOUT_SECONDS,
        )

    handler.__name__ = f"{canonical.replace('-', '_')}_handler"
    return handler


def _build_sync_tool(adapter: ToolAdapter, definition: dict[str, Any]) -> FunctionTool:
    title, annotations = annotations_for(adapter.canonical, _mcp_name_for(adapter))
    return FunctionTool(
        fn=_make_sync_handler(adapter.canonical, adapter.default_action),
        name=_mcp_name_for(adapter),
        title=title,
        description=_description_for(adapter),
        parameters=build_input_schema(adapter.canonical, adapter, definition),
        annotations=annotations,
    )


def _build_async_tool(adapter: ToolAdapter, definition: dict[str, Any]) -> FunctionTool:
    canonical = adapter.canonical
    schema = build_input_schema(canonical, adapter, definition, actions=(adapter.default_action,))
    schema["properties"]["wait"] = {
        "type": "boolean",
        "description": (
            "If false (default), returns a task_id immediately; follow up with get_task_status or "
            f"get_task_result. If true, waits up to {DEFAULT_WAIT_TIMEOUT_SECONDS}s for the result; "
            "if the task is still running then, returns status 'still_running' with the task_id "
            "rather than an error. Every call to this tool starts a new, separately charged task."
        ),
    }
    title, annotations = annotations_for(canonical, _mcp_name_for(adapter))
    return FunctionTool(
        fn=_make_async_handler(canonical, adapter.default_action),
        name=_mcp_name_for(adapter),
        title=title,
        description=_description_for(adapter),
        parameters=schema,
        annotations=annotations,
    )


def build_tools(definitions: DefinitionsManager) -> list[FunctionTool]:
    tools: list[FunctionTool] = []
    for adapter in TOOL_ADAPTERS.values():
        if adapter.canonical in MCP_EXCLUDED_TOOLS:
            continue
        entry = definitions.get_tool(adapter.canonical)
        definition = entry.get("definition") or {}
        if adapter.async_likely:
            tools.append(_build_async_tool(adapter, definition))
        else:
            tools.append(_build_sync_tool(adapter, definition))
    return tools
