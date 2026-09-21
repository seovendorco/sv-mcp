"""End-to-end smoke test: calls every SV MCP tool once through the real MCP layer.

Runs the server in-process (stdio mode, no OAuth) against the live SV API, so it
spends points: roughly 10 per chargeable call, ~200 for a full run. Uses the API
key from SV_API_KEY or `sv auth set` - it is never printed.

    python scripts/smoke_test.py                  # every tool
    python scripts/smoke_test.py seogpt ranklens  # only these
    python scripts/smoke_test.py --list           # show the cases, call nothing

Async tools are started with wait=false and then followed with get_task_status /
get_task_result, which also tests the two task tools. Calls are sequential with a
pause between them, to stay inside the API's 1 request/second limit.

Exit code 0 when every case passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any

from fastmcp import Client
from fastmcp.exceptions import ToolError

from sv_mcp.server import create_server

SITE = "https://seovendor.co"
DOMAIN = "seovendor.co"

# (label, tool, arguments). Labels are unique so a tool can have several cases.
CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("better-keywords", "better-keywords", {"keyword": "seo audit"}),
    ("content-quality", "content-quality", {"keyword": "seo services", "url": SITE}),
    (
        "content-transformer",
        "content-transformer",
        {"text": "We help small businesses get found on Google with honest, affordable SEO.", "keyword": "affordable seo"},
    ),
    ("core-analysis", "core-analysis", {"keyword": "seo services", "url": SITE}),
    # Regression check for a reported bug: keyword only, no url.
    ("core-analysis (keyword only)", "core-analysis", {"keyword": "seo services"}),
    ("insight-igniter", "insight-igniter", {"web": DOMAIN}),
    ("preliminaryaudit", "preliminaryaudit", {"url": SITE}),
    ("ranklens", "ranklens", {"entity": "seo services", "web": DOMAIN}),
    # google.com needs brand: without it the API now returns a VALIDATION_ERROR on brand
    # (it used to return "not ranked" with success true).
    ("ranklens (with brand)", "ranklens", {"entity": "search engine", "web": "google.com", "brand": "Google"}),
    ("seogpt", "seogpt", {"keyword": "seo audit", "type": 1}),
    ("topical-authority", "topical-authority", {"keyword": "technical seo"}),
    ("top-competitors", "top-competitors", {"keyword": "seo audit"}),
    ("marketplace-services", "marketplace-services", {"keyword": "seo"}),
    # Regression check for a reported bug: empty result for "audit".
    ("marketplace-services (audit)", "marketplace-services", {"keyword": "audit"}),
    ("geogptaudit", "geogptaudit", {"keyword": "seo services", "url": SITE}),
    ("prose", "prose", {"topic": "How to run a basic SEO audit", "keyword": "seo audit"}),
    ("seogptcompare", "seogptcompare", {"keyword": "seo services", "url": SITE}),
    ("seogptmapping", "seogptmapping", {"keyword": "seo services, seo audit", "url": SITE}),
]

PAUSE_SECONDS = 1.5  # between calls; the SV API allows 1 request/second per key
POLL_SECONDS = 10
TASK_TIMEOUT_SECONDS = 15 * 60
DONE = {"done", "complete", "completed", "success", "succeeded", "finished"}
FAILED = {"error", "failed", "failure", "cancelled", "canceled"}


def _payload(result: Any) -> Any:
    """The tool's JSON output from a fastmcp CallToolResult."""
    if getattr(result, "structured_content", None) is not None:
        data = result.structured_content
        # FastMCP wraps non-object return values as {"result": ...}.
        return data.get("result", data) if isinstance(data, dict) and set(data) == {"result"} else data
    text = "".join(getattr(block, "text", "") for block in result.content)
    try:
        return json.loads(text)
    except ValueError:
        return text


def _is_empty(data: Any) -> bool:
    if data in (None, "", [], {}):
        return True
    if isinstance(data, dict):
        return all(_is_empty(v) for k, v in data.items() if k not in ("success", "status", "tool", "action", "meta"))
    return False


def _status(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("status", "state"):
            if isinstance(data.get(key), str):
                return data[key].lower()
        inner = data.get("data")
        if isinstance(inner, dict):
            return _status(inner)
    return ""


def _find_task_id(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("task_id", "taskid", "taskId"):
            if data.get(key):
                return str(data[key])
        for value in data.values():
            found = _find_task_id(value)
            if found:
                return found
    return None


def _summary(data: Any, limit: int = 160) -> str:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


async def _call(client: Client, tool: str, args: dict[str, Any]) -> tuple[bool, Any]:
    await asyncio.sleep(PAUSE_SECONDS)
    try:
        return True, _payload(await client.call_tool(tool, args))
    except ToolError as exc:
        return False, str(exc)


async def _follow_task(client: Client, tool: str, task_id: str) -> tuple[bool, str]:
    deadline = time.monotonic() + TASK_TIMEOUT_SECONDS
    status = ""
    while time.monotonic() < deadline:
        ok, data = await _call(client, "get_task_status", {"task_id": task_id, "tool": tool})
        if not ok:
            return False, f"get_task_status failed: {data}"
        status = _status(data)
        if status in FAILED:
            return False, f"task {status}: {_summary(data)}"
        if status in DONE:
            break
        await asyncio.sleep(POLL_SECONDS)
    else:
        return False, f"still '{status}' after {TASK_TIMEOUT_SECONDS // 60} min"

    ok, data = await _call(client, "get_task_result", {"task_id": task_id, "tool": tool})
    if not ok:
        return False, f"get_task_result failed: {data}"
    if _is_empty(data):
        return False, f"empty result: {_summary(data)}"
    return True, _summary(data)


async def run(selected: list[str]) -> int:
    cases = [c for c in CASES if not selected or c[0] in selected or c[1] in selected]
    results: list[tuple[str, bool, float, str]] = []
    async with Client(create_server()) as client:
        exposed = {t.name for t in await client.list_tools()}
        print(f"{len(exposed)} tools exposed: {', '.join(sorted(exposed))}\n")
        if "seo-image" in exposed:
            results.append(("seo-image not exposed", False, 0.0, "seo-image is in the tool list"))

        for label, tool, args in cases:
            started = time.monotonic()
            print(f"- {label} ...", flush=True)
            ok, data = await _call(client, tool, args)
            if not ok:
                detail = data
            elif (task_id := _find_task_id(data)) and _status(data) not in DONE:
                print(f"    task {task_id} started, polling", flush=True)
                ok, detail = await _follow_task(client, tool, task_id)
            elif _is_empty(data):
                ok, detail = False, f"empty result: {_summary(data)}"
            else:
                detail = _summary(data)
            elapsed = time.monotonic() - started
            results.append((label, ok, elapsed, detail))
            print(f"    {'PASS' if ok else 'FAIL'} ({elapsed:.0f}s) {detail}", flush=True)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    for label, _, _, detail in failed:
        print(f"  FAIL {label}: {detail}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("only", nargs="*", help="case labels or tool names to run (default: all)")
    parser.add_argument("--list", action="store_true", help="list the cases without calling anything")
    options = parser.parse_args()
    if options.list:
        for label, tool, args in CASES:
            print(f"{label:32} {tool:22} {json.dumps(args)}")
        return
    sys.exit(asyncio.run(run(options.only)))


if __name__ == "__main__":
    main()
