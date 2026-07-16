# sv-mcp

MCP server exposing SV's content/SEO tools to AI agents (Claude Desktop, Claude Code, other MCP hosts), built directly on top of the `sv-cli` core library — no duplicated resolver, auth, or async-task logic.

See `plan.md` for the build plan and current phase status.

## Local dev setup (stdio, single-user)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
export SV_API_KEY=...
python -m sv_mcp.server
```

## HTTP mode (hosted, multi-user OAuth)

For a hosted deployment (e.g. `mcp.seovendor.co`) reachable by multiple users via
Claude/ChatGPT, set `SV_MCP_TRANSPORT=http` instead of the stdio default. In this
mode each caller authenticates via OAuth against SEOB's login system, and their
own SV API key is resolved per-request — no single `SV_API_KEY` for the whole
process.

Copy `.env.example` to `.env` (or set these directly in your process manager)
and fill in the values:

```bash
cp .env.example .env
pip install .
python -m sv_mcp.server
```

`SV_MCP_OAUTH_CLIENT_SECRET` is required in this mode — it's the client_secret
`sv-mcp` was registered with in SEOB's `oauth_clients` table. The server will
fail fast with a clear error if it's missing.

When registering the MCP connector in the client (e.g. claude.ai's custom
connector UI), use the base URL with `/mcp` appended, e.g.
`https://mcp.seovendor.co/mcp` — that's where FastMCP mounts the actual MCP
protocol endpoint, separate from the OAuth callback/discovery routes also
served on this domain.
