"""Convert a live sv_cli tool definition into an MCP inputSchema.

sv_cli's own `resolver.extract_option_sets()` finds the enum/option data;
this module's job is only to shape that into JSON Schema and pick sane
property names, not to re-derive it.
"""

from __future__ import annotations

from typing import Any

from sv_cli.adapters import COMMON_FIELD_ALIASES, ToolAdapter
from sv_cli.resolver import Candidate, extract_option_sets, normalize_field, resolve_api_field

# "k" is the API key field - injected server-side from SV_API_KEY, never model input.
# "action" is handled separately, from the adapter's curated action list.
# "task_id" only applies to the status/result actions, which sv-mcp routes through
# the dedicated get_task_status/get_task_result tools instead of this tool's schema.
EXCLUDED_API_FIELDS = {"k", "action", "task_id"}

# Known fallback/alias fields that duplicate another field's meaning for a specific
# tool - confirmed against the real API backend source, not guessable from the
# definitions data alone (they're genuinely different api_field strings, so the
# generic dedup logic in _display_names() can't detect this on its own).
TOOL_SPECIFIC_ALIAS_FIELDS: dict[str, set[str]] = {
    # "imagebackground" is a fallback alias for "background" (confirmed against
    # seoai/api/seo-image/index.php) - exposing both is redundant, not useful.
    "seo-image": {"imagebackground"},
    # "kw"/"keyword" are deprecated input aliases of "entity" (confirmed against
    # seoai/api/ranklens/index.php) kept server-side only for backward compatibility
    # with existing raw API callers - a model should only ever see "entity".
    "ranklens": {"kw", "keyword"},
}

API_TYPE_TO_JSON_TYPE = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
}


def _real_field_names(definition: Any) -> set[str]:
    names: set[str] = set()
    for item in _api_input_items(definition):
        field = item.get("field")
        if isinstance(field, str):
            names.add(normalize_field(field))
    return names


def _required_api_fields(definition: Any) -> set[str]:
    required: set[str] = set()
    for item in _api_input_items(definition):
        field = item.get("field")
        if isinstance(field, str) and str(item.get("required", "")).strip().lower() in {"yes", "true", "required"}:
            required.add(normalize_field(field))
    return required


def _declared_json_type(definition: Any, api_field: str) -> str:
    for item in _api_input_items(definition):
        if normalize_field(str(item.get("field", ""))) == api_field:
            return API_TYPE_TO_JSON_TYPE.get(str(item.get("type", "")).lower(), "string")
    return "string"


def _field_description(definition: Any, api_field: str) -> str | None:
    """The real API's own prose description for a plain (non-enum) field, if any.

    Enum fields get their description built from their actual options instead
    (see _enum_schema) - the raw description for those is a labeled-options list,
    not prose, so it isn't useful here.
    """

    for item in _api_input_items(definition):
        if normalize_field(str(item.get("field", ""))) == api_field:
            description = item.get("description")
            return description if isinstance(description, str) else None
    return None


def _api_input_items(definition: Any) -> list[dict[str, Any]]:
    items = definition.get("api_input") if isinstance(definition, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _display_names(tool: str, adapter: ToolAdapter, definition: Any, target_fields: set[str]) -> dict[str, str]:
    """Best human-friendly property name per real api_field; falls back to the raw field name."""

    alias_keys = set(COMMON_FIELD_ALIASES) | set(adapter.field_aliases)
    candidates_by_field: dict[str, list[str]] = {}
    for friendly in sorted(alias_keys):
        api_field, _candidates = resolve_api_field(tool, friendly, definition)
        if api_field in target_fields:
            candidates_by_field.setdefault(api_field, []).append(friendly)

    display: dict[str, str] = {}
    for api_field in target_fields:
        options = candidates_by_field.get(api_field, [])
        exact = [name for name in options if normalize_field(name) == api_field]
        display[api_field] = exact[0] if exact else (sorted(options)[0] if options else api_field)
    return display


# Some real fields have 100-300+ options (e.g. content-transformer's `type`: 333 options,
# 8500+ chars of labels). Spelling every label out gets sent to the model on every tool
# listing, not just when the tool is actually called - real, quantifiable context cost that
# scales with tool count (Anthropic Software Directory Policy 5B: be frugal with tokens). The
# set of valid values always stays complete; only the human-readable label text in
# `description` gets capped.
MAX_ENUM_DESCRIPTION_CHARS = 1500


def _contiguous_int_range(values: list[Any]) -> tuple[int, int] | None:
    """(lo, hi) if values are exactly the integers lo..hi, else None."""
    if not values or not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return None
    lo, hi = min(values), max(values)
    if len(values) == hi - lo + 1 and len(set(values)) == len(values):
        return lo, hi
    return None


def _enum_schema(candidates: list[Candidate], json_type: str) -> dict[str, Any]:
    values: list[Any] = []
    labels: list[str] = []
    seen: set[Any] = set()
    for candidate in candidates:
        if candidate.id in seen:
            continue
        seen.add(candidate.id)
        values.append(candidate.id)
        labels.append(f"{candidate.id}={candidate.label}")

    # Integer option ids are always a contiguous 0..N range (they're array positions in the
    # API's option lists). minimum/maximum validates exactly the same set as a full `enum`
    # list, without sending hundreds of numbers the description already lists - saves ~1.4K
    # tokens across the tool list. Anything that isn't a contiguous int range keeps `enum`.
    int_range = _contiguous_int_range(values)
    valid_values = f"any id from {int_range[0]} to {int_range[1]}" if int_range else "all values in `enum`"

    description = "; ".join(labels)
    if len(description) > MAX_ENUM_DESCRIPTION_CHARS:
        shown: list[str] = []
        length = 0
        for label in labels:
            if length + len(label) + 2 > MAX_ENUM_DESCRIPTION_CHARS:
                break
            shown.append(label)
            length += len(label) + 2
        remaining = len(labels) - len(shown)
        description = (
            "; ".join(shown)
            + f"; ... and {remaining} more options not shown. {valid_values[0].upper()}"
            f"{valid_values[1:]} is valid even though not labeled here - if the user's request "
            "doesn't clearly match one of the examples above, ask them which specific option "
            "they want rather than guessing an unlabeled id."
        )
    if int_range:
        return {"type": json_type, "minimum": int_range[0], "maximum": int_range[1], "description": description}
    return {"type": json_type, "enum": values, "description": description}


def build_input_schema(
    tool: str,
    adapter: ToolAdapter,
    definition: Any,
    *,
    actions: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Build an MCP inputSchema for one tool family from its live sv_cli definition.

    `actions` overrides which of the adapter's actions this particular MCP tool
    advertises - e.g. an async creation tool only wants "create-task", not the
    status/result actions that get their own dedicated get_task_status/get_task_result
    tools instead.
    """

    option_sets = extract_option_sets(definition)
    target_fields = (set(option_sets) | _real_field_names(definition)) - EXCLUDED_API_FIELDS
    target_fields -= TOOL_SPECIFIC_ALIAS_FIELDS.get(tool, set())
    required_fields = _required_api_fields(definition)
    display_names = _display_names(tool, adapter, definition, target_fields)

    properties: dict[str, Any] = {}
    required: list[str] = []

    exposed_actions = [action for action in (actions or adapter.actions) if action != "raw"]
    if len(exposed_actions) > 1:
        # The live definition's own "action" field often documents what each action does
        # (e.g. ranklens: "rank: Generate RankLens report. competitors: Find RankLens
        # competitors.") - prefer that real text over a bare list of action names.
        action_candidates = {str(c.id): c.label for c in option_sets.get("action", [])}
        action_desc = "; ".join(
            f"{action}: {action_candidates[action]}" if action in action_candidates else action
            for action in exposed_actions
        )
        properties["action"] = {
            "type": "string",
            "enum": exposed_actions,
            "description": f"{action_desc}. Defaults to '{adapter.default_action}' when omitted.",
        }

    for api_field in sorted(target_fields):
        candidates = option_sets.get(api_field)
        declared_type = _declared_json_type(definition, api_field)

        name = display_names[api_field]
        if candidates:
            item_type = "integer" if all(isinstance(c.id, int) for c in candidates) else "string"
            if declared_type == "array":
                # Multi-select: e.g. better-keywords' researchtype/kwcompetition. Requires
                # sv_cli.resolver.resolve_enum_value() to handle list-valued input, which it
                # now does - each item gets resolved individually against the same candidates.
                properties[name] = {"type": "array", "items": _enum_schema(candidates, item_type)}
            else:
                properties[name] = _enum_schema(candidates, item_type)
        else:
            properties[name] = {"type": declared_type}
            description = _field_description(definition, api_field)
            if description:
                properties[name]["description"] = description
        if api_field in required_fields:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
