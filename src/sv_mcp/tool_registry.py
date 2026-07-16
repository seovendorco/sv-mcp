"""Builds MCP FunctionTool objects from sv_cli's live tool definitions.

Phase 3: registers every family in sv_cli.adapters.TOOL_ADAPTERS, partitioned
into the sync and async paths by each adapter's async_likely flag - not a
hand-picked list anymore. A new tool added to sv_cli's adapters.py appears
here automatically on next restart, picking up TOOL_DESCRIPTIONS' fallback
text until someone writes it a real one.
"""

from __future__ import annotations

from typing import Any

from fastmcp.tools import FunctionTool
from sv_cli.adapters import TOOL_ADAPTERS, ToolAdapter
from sv_cli.definitions import DefinitionsManager

from .execution import DEFAULT_WAIT_TIMEOUT_SECONDS, call_sv_tool
from .schemas import build_input_schema

# Hand-authored, not pulled from the API: sv_cli's tool definitions only carry
# per-field descriptions, no tool-level summary. Written explicitly enough that
# a model prefers calling the tool over improvising the task itself - a terse
# "SV 'seogpt2' tool" description isn't enough signal that this returns real,
# publish-ready generated text rather than being some kind of metadata lookup.
# Grounded in each tool's real api_output schema (what it actually returns),
# not guessed from the tool name alone.
TOOL_DESCRIPTIONS: dict[str, str] = {
    "better-keywords": (
        "Research real SEO keyword opportunities for a seed keyword, using SV's own keyword "
        "data (not a language-model guess). Returns keyword variants with search volume, CPC, "
        "competition score, and buyer intent. Use this whenever the user wants keyword research "
        "or keyword ideas."
    ),
    "content-quality": (
        "Score a live URL's actual content against SV's HCU/EEAT quality rubric for a target "
        "keyword. Returns up to 15 scored questions per URL (0-100 each, with a reasoning string), "
        "and can compare two URLs at once via url_b. Use this for any content-quality/EEAT "
        "evaluation of a real page - it reads and scores the page itself."
    ),
    "content-transformer": (
        "Rewrite or reformat existing content text (e.g. into a meta title, product description, "
        "landing page copy) through SV's content engine. Takes the source text as input and returns "
        "the rewritten version. IMPORTANT: always call this tool for a rewrite/reformat request, even "
        "though it's the kind of short task you could plausibly just answer directly - SV's engine "
        "applies its own SEO-specific rewriting rules (keyword placement, length targets, tone) that "
        "differ from a generic rewrite, and the user asking for this specifically wants SV's version, "
        "not your own. Don't rewrite the text yourself instead of calling this. For generating new "
        "content from scratch (not rewriting existing text) use seogpt (short-form) or seogpt2 "
        "(long-form) instead."
    ),
    "core-analysis": (
        "Run a detailed technical/on-page SEO analysis of a URL - returns HTTP status, page load "
        "speed, and structured data for the title tag, meta description, H1s, H2s, and keyword usage. "
        "Use this for a structural breakdown of a specific page's on-page SEO elements. For a single "
        "overall score instead of a structural breakdown, use preliminaryaudit."
    ),
    "insight-igniter": (
        "Fast, synchronous: discover what entities/topics AI engines already associate with a website "
        "- you give it a URL and nothing else, and it tells you what comes back. Returns one result "
        "set per AI engine queried. Use this whenever the user asks an open-ended question like 'what "
        "does AI associate with this site' or 'what entities show up for this brand' - you don't need "
        "to know or supply any entities/keywords yourself first. This is different from geogptaudit: "
        "that one is a slow (several-minute) async task that scores how well a site performs for "
        "entities/keywords YOU already specify - only reach for geogptaudit if the user explicitly "
        "asks for a GEO audit or visibility score against specific known entities, not for general "
        "'what is AI associating with this site' questions, which this tool answers much faster."
    ),
    "preliminaryaudit": (
        "Run a quick, scored SEO audit of a URL - returns an overall score out of a maximum possible "
        "score across a set of automated checks (canonical tags, blocking meta tags, load speed, "
        "etc.). Use this for a fast pass/fail-style health score. For a structural element-by-element "
        "breakdown instead of a single score, use core-analysis."
    ),
    "ranklens": (
        "Sample how a website ranks for a keyword across repeated AI-engine queries (the 'rank' "
        "action) - returns one ranking data point per sample. Follow up with the 'competitors' "
        "action (passing the mgptid from a prior rank result) to see which competitors showed up in "
        "those same samples."
    ),
    "seo-image": (
        "Generate an actual SEO-optimized image (e.g. a featured image or social graphic) through "
        "SV's image engine and return a URL to the generated file - this IS SV's image generator, not "
        "a description of what an image could look like. Prefer this over describing/suggesting an "
        "image yourself when the user wants a real generated image."
    ),
    "seogpt": (
        "Generate short-form SEO content (e.g. meta titles/descriptions, short product descriptions) "
        "synchronously through SV's content engine, returning the generated text directly with no "
        "waiting or polling - this IS SV's content generator for quick snippets. IMPORTANT: always "
        "call this tool for a short SEO content request, even though writing one short title or "
        "description feels like something you could just answer directly - SV's engine applies its "
        "own SEO-specific tuning (character-limit compliance, keyword placement rules) that a generic "
        "answer wouldn't include, and the user asking for this wants SV's version specifically. Don't "
        "write the title/description yourself instead of calling this. Can generate multiple "
        "variations at once via qty. For longer-form content (full articles, blog posts), which is "
        "async and takes several minutes, use seogpt2 instead."
    ),
    "topical-authority": (
        "Generate a topical content plan for a keyword: suggested article topics and subtopics to "
        "build topical authority (the 'topics' action), or expand chosen topics into content pointers "
        "(the 'content' action). Use this for content strategy/planning, not for generating finished "
        "articles - for that, use seogpt2."
    ),
    "top-competitors": (
        "Find the top-ranking competitor URLs for a keyword - a fast, lightweight competitor list. "
        "For a fuller comparative analysis against a specific target URL (not just a list), use "
        "seogptcompare instead."
    ),
    "marketplace-services": (
        "Search SV's marketplace for purchasable services (SEO/PPC/DEV, etc.) matching a search term, "
        "with optional price/series/category filters. Use this to find SV services to buy, not for "
        "SEO analysis or content generation."
    ),
    "geogptaudit": (
        "Slow (commonly several minutes) async audit: scores how well a domain or page performs in "
        "AI-generated answers (ChatGPT, Gemini, AI Overviews, etc.) for a set of target entities/"
        "keywords YOU already have in mind - this is not a traditional SEO crawl. Only use this when "
        "the user explicitly asks for a GEO audit, AI-visibility score, or similar against specific "
        "known entities. For an open-ended 'what does AI associate with this site' question where no "
        "entities are specified upfront, use insight-igniter instead - it's synchronous and much "
        "faster. Creates a task and returns its task_id immediately by default - see the wait "
        "parameter to block for the result instead."
    ),
    "seogpt2": (
        "Generate actual publish-ready, long-form SEO content (blog posts, full articles, etc.) "
        "through SV's content engine and return the generated text itself - this IS SV's content "
        "generator, not a summary, outline, or metadata lookup. Prefer this over writing the "
        "content yourself whenever the user asks for SV-generated or SEO-optimized content. Async: "
        "creates a task and returns its task_id immediately by default (generation commonly takes "
        "several minutes) - see the wait parameter to block for the result instead. For short-form "
        "content (meta titles/descriptions), use seogpt instead - it's synchronous and much faster."
    ),
    "seogptcompare": (
        "Compare how a target URL is positioned for a keyword against its real competitors, using "
        "SV's own competitive analysis (not a manual review). Async: creates a task and returns its "
        "task_id immediately by default - see the wait parameter to block for the result instead."
    ),
    "seogptmapping": (
        "Map a list of keywords to the best-matching existing pages on a target domain - useful for "
        "internal linking or content-gap analysis. Async: creates a task and returns its task_id "
        "immediately by default - see the wait parameter to block for the result instead."
    ),
}


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
    return FunctionTool(
        fn=_make_sync_handler(adapter.canonical, adapter.default_action),
        name=adapter.canonical,
        description=_description_for(adapter),
        parameters=build_input_schema(adapter.canonical, adapter, definition),
    )


def _build_async_tool(adapter: ToolAdapter, definition: dict[str, Any]) -> FunctionTool:
    canonical = adapter.canonical
    schema = build_input_schema(canonical, adapter, definition, actions=(adapter.default_action,))
    schema["properties"]["wait"] = {
        "type": "boolean",
        "description": (
            "Defaults to false: this call returns the task_id right away, without waiting for the "
            "task to finish. Follow up with get_task_status(task_id=...) or get_task_result(task_id=...) "
            "to check progress or fetch the finished result once ready - call those again, spaced out, "
            "if the task isn't done yet. Set wait=true instead to block in this same call for up to "
            f"{DEFAULT_WAIT_TIMEOUT_SECONDS}s and get the result directly, if the task is expected to "
            "be quick. Either way: never call this tool again for the same request just because a "
            "previous attempt is still running or slow - that creates a second, duplicate, "
            "separately-charged task. If a wait=true call runs out of time, it still returns "
            "successfully (not an error) with the task_id and a status of 'still_running' - follow up "
            "with get_task_status/get_task_result the same way."
        ),
    }
    return FunctionTool(
        fn=_make_async_handler(canonical, adapter.default_action),
        name=canonical,
        description=_description_for(adapter),
        parameters=schema,
    )


def build_tools(definitions: DefinitionsManager) -> list[FunctionTool]:
    tools: list[FunctionTool] = []
    for adapter in TOOL_ADAPTERS.values():
        entry = definitions.get_tool(adapter.canonical)
        definition = entry.get("definition") or {}
        if adapter.async_likely:
            tools.append(_build_async_tool(adapter, definition))
        else:
            tools.append(_build_sync_tool(adapter, definition))
    return tools
