"""MCP tool titles and behavior annotations.

Required by Anthropic's Software Directory Policy (5E): every tool needs a title,
readOnlyHint and destructiveHint.

Classification rule: a tool is read-only unless it saves something to the user's
SV account - a task, an article, a report in their history. Spending points is
billing, not a change the tool makes. Internal caches don't count either, since
the user never sees them. Checked per tool against what each upstream endpoint
actually writes:
  - create a task or saved record in the account: prose (seogpt2), geogptaudit,
    seogptcompare, seogptmapping, and preliminaryaudit (saves the audit to the
    account's history, which SEOB shows as a score trend)
  - everything else writes nothing, or only to internal caches with no user or
    agency column

No SV tool deletes or overwrites user data, so destructiveHint is always false.
All tools reach external services (web pages, AI engines, search data), so
openWorldHint is always true.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
# Each call creates a new task/record, so repeating it is not idempotent.
WRITES = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}

# (title, profile), keyed by sv_cli canonical tool name (like TOOL_DESCRIPTIONS).
TOOL_META: dict[str, tuple[str, dict[str, bool]]] = {
    "better-keywords": ("Research Keywords", READ_ONLY),
    "content-quality": ("Score Content Quality (E-E-A-T)", READ_ONLY),
    "content-transformer": ("Rewrite Content", READ_ONLY),
    "core-analysis": ("Analyze On-Page SEO", READ_ONLY),
    "insight-igniter": ("Find Entities AI Associates with a Site", READ_ONLY),
    "ranklens": ("AI Brand Visibility (RankLens)", READ_ONLY),
    "seogpt": ("Generate Short SEO Copy (SEO GPT)", READ_ONLY),
    "topical-authority": ("Plan Topical Authority Articles", READ_ONLY),
    "top-competitors": ("Find Top Competitors", READ_ONLY),
    "marketplace-services": ("Search SV Marketplace", READ_ONLY),
    "preliminaryaudit": ("Run SEO Health Check", WRITES),
    "geogptaudit": ("Start GEO Audit", WRITES),
    "seogpt2": ("Write Long-Form Article (Prose)", WRITES),
    "seogptcompare": ("Get SEO Strategy (SEO Strategist)", WRITES),
    "seogptmapping": ("Map Keywords to Pages", WRITES),
}

TASK_TOOL_META: dict[str, str] = {
    "get_task_status": "Check Task Status",
    "get_task_result": "Get Task Result",
}


def annotations_for(canonical: str, fallback_title: str) -> tuple[str, ToolAnnotations]:
    """(title, annotations) for a tool family.

    A tool sv_cli adds before it gets an entry here falls back to WRITES - the
    conservative choice the policy prefers when unsure - with a generic title,
    rather than stopping the server. tests/test_tool_registry.py fails CI until
    it gets a real entry.
    """
    title, profile = TOOL_META.get(canonical, (fallback_title, WRITES))
    return title, ToolAnnotations(title=title, **profile)


def task_tool_annotations(name: str) -> tuple[str, ToolAnnotations]:
    title = TASK_TOOL_META[name]
    return title, ToolAnnotations(title=title, **READ_ONLY)
