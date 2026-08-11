"""Tests for schemas.build_input_schema() against real, frozen tool definitions.

Most of the bugs found during manual testing this session lived in this module -
these tests exist to lock in that already-verified behavior so it can't silently
regress later.
"""

from __future__ import annotations

import json
from pathlib import Path

from sv_cli.adapters import TOOL_ADAPTERS

from sv_mcp.schemas import build_input_schema

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _schema(definitions, tool):
    return build_input_schema(tool, TOOL_ADAPTERS[tool], definitions[tool])


def test_better_keywords_properties_and_required(definitions):
    schema = _schema(definitions, "better-keywords")
    assert schema["required"] == ["keyword"]
    assert "researchtype" in schema["properties"]
    assert "kwcompetition" in schema["properties"]
    assert len(schema["properties"]["language"]["enum"]) == 40


def test_array_enum_field_builds_array_of_enum_shape(definitions):
    schema = _schema(definitions, "better-keywords")
    researchtype = schema["properties"]["researchtype"]
    assert researchtype["type"] == "array"
    assert researchtype["items"]["type"] == "integer"
    assert len(researchtype["items"]["enum"]) == 66

    kwcompetition = schema["properties"]["kwcompetition"]
    assert kwcompetition["type"] == "array"
    assert len(kwcompetition["items"]["enum"]) == 32


def test_oversized_enum_description_is_capped_but_enum_stays_complete(definitions):
    schema = _schema(definitions, "content-transformer")
    type_prop = schema["properties"]["type"]
    assert len(type_prop["enum"]) == 333
    # Labels are capped at MAX_ENUM_DESCRIPTION_CHARS (1500); the trailing "N more options"
    # note is appended after that, so the total lands a bit above 1500, well under the
    # ~8500 chars an uncapped 333-option description would be.
    assert 1500 < len(type_prop["description"]) < 2000
    assert "more options not shown" in type_prop["description"]


def test_excluded_fields_never_appear(definitions):
    for tool in TOOL_ADAPTERS:
        schema = _schema(definitions, tool)
        assert "k" not in schema["properties"], f"{tool} leaked the API key field"
        assert "action" not in schema["properties"] or len(
            [a for a in TOOL_ADAPTERS[tool].actions if a != "raw"]
        ) > 1
        assert "task_id" not in schema["properties"], f"{tool} leaked task_id"


def test_seo_image_excludes_imagebackground_alias(definitions):
    schema = _schema(definitions, "seo-image")
    assert "imagebackground" not in schema["properties"]
    assert "background" in schema["properties"]
    assert len(schema["properties"]["background"]["enum"]) == 52


def test_multi_action_tools_get_real_per_action_descriptions(definitions):
    schema = _schema(definitions, "ranklens")
    action = schema["properties"]["action"]
    assert set(action["enum"]) == {"rank", "competitors"}
    assert "Generate RankLens report" in action["description"]
    assert "Find RankLens competitors" in action["description"]


def test_single_action_tool_has_no_action_property(definitions):
    schema = _schema(definitions, "preliminaryaudit")
    assert "action" not in schema["properties"]

    # topical-authority was a two-action tool (topics/content); content was removed
    # because it duplicated topics's real behavior (see seoai's topical-authority
    # fix) - now single-action, so no action property should be exposed either.
    schema = _schema(definitions, "topical-authority")
    assert "action" not in schema["properties"]


def test_plain_field_descriptions_surfaced_from_real_api(definitions):
    schema = _schema(definitions, "seogpt2")
    # Topic (the article subject) and KW (optional keywords to include) are two
    # distinct real fields - "topic" must carry Topic's constraint, "keyword"
    # must carry KW's, never the other way around (see adapters.py's seogpt2
    # override and its regression test in sv_cli/tests/test_executor.py).
    assert "12 to 200 characters" in schema["properties"]["topic"]["description"]
    assert "up to 5 keywords" in schema["properties"]["keyword"]["description"]
    assert schema["required"] == ["topic"]


def test_action_override_restricts_exposed_actions(definitions):
    # Async creation tools only want their default_action exposed (see tool_registry.py),
    # not the get-task-status/get-result actions handled by the dedicated task tools.
    adapter = TOOL_ADAPTERS["seogpt2"]
    schema = build_input_schema(
        "seogpt2", adapter, definitions["seogpt2"], actions=(adapter.default_action,)
    )
    assert "action" not in schema["properties"]


def test_ranklens_entity_rename_excludes_deprecated_kw_keyword_aliases():
    """Once seoai ships the entity rename, only "entity" should reach the model -

    "kw"/"keyword" become deprecated server-side input aliases (kept for backward
    compatibility with raw API callers), not something a model should also see as
    a separate, redundant parameter. Uses a fixture shaped like ranklens's live
    definition will look post-deployment (see seoai/api/ranklens/index.php and
    api_definitions.php's entity/keyword schema changes).
    """

    fixture = json.loads((FIXTURES_DIR / "ranklens_post_deploy.json").read_text())
    schema = build_input_schema("ranklens", TOOL_ADAPTERS["ranklens"], fixture)
    assert "entity" in schema["properties"]
    assert "kw" not in schema["properties"]
    assert "keyword" not in schema["properties"]
    assert schema["required"] == ["entity", "web"]


def test_all_16_tools_build_without_error(definitions):
    for tool, adapter in TOOL_ADAPTERS.items():
        schema = build_input_schema(tool, adapter, definitions[tool])
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert isinstance(schema["properties"], dict) and schema["properties"]
