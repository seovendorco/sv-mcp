"""Shared pytest fixtures.

`definitions()` loads a frozen, real snapshot of sv_cli tool definitions
(tests/fixtures/definitions_snapshot.json) once per test session - no
network access or SV_API_KEY needed to run this suite. The snapshot holds
all 16 TOOL_ADAPTERS entries' real `definition` payloads, captured from
~/.sv/cache/definitions.json (the same cache this project's manual testing
was validated against throughout development). To refresh it later, re-run
the extraction: for each canonical in sv_cli.adapters.TOOL_ADAPTERS, pull
cache["tools"][canonical]["definition"] and write the resulting dict out
as this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def definitions() -> dict[str, Any]:
    with open(FIXTURES_DIR / "definitions_snapshot.json") as f:
        return json.load(f)
