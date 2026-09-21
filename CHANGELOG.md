# Changelog

## 0.2.0

First release on PyPI and the MCP Registry.

- Every tool now has a human-readable title and MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`). Tools that save work to the SV account (`prose`, `geogptaudit`, `seogptcompare`, `seogptmapping`, `preliminaryaudit`) are marked as not read-only.
- Requires sv-cli 0.8.0, which retries automatically when the SV API rate limit (1 request per second per API key) is reached.
- Removed `seo-image` from the MCP tool list. AI image generation stays available through the SV API and SV CLI.
- Rewrote tool descriptions to state what each tool does and when to use it, without model-directed instructions.
- Tool errors now return the SV API's own message, field and error code, with a suggested next step, instead of raw JSON.
- Integer option fields are sent as a `minimum`/`maximum` range instead of a full list, reducing the size of the tool list by about a third.
- Added LICENSE, SECURITY.md, CONTRIBUTING.md and CODE_OF_CONDUCT.md.

## 0.1.0

- Initial MCP server built on the sv-cli core library: stdio mode with `SV_API_KEY`, and hosted Streamable HTTP mode with OAuth.
- Tool families generated from the live SV API definitions, plus `get_task_status` and `get_task_result` for async tasks.
- `seogpt2` exposed as `prose`.
- Calls identify themselves to the SV API as MCP clients for usage tracking.
