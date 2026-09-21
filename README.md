# SV MCP

<!-- mcp-name: co.seovendor/sv-mcp -->

SV MCP is the [Model Context Protocol](https://modelcontextprotocol.io) server for the SV API. It gives Claude, Cursor, VS Code, Windsurf and other MCP clients SV's SEO and GEO tools: keyword research, page audits, AI-visibility (GEO) audits, competitor analysis and content generation.

It is built on the same core library as [SV CLI](https://github.com/seovendorco/sv-cli), so both behave the same way against the SV API.

- **Server URL:** `https://mcp.seovendor.co`
- **Transport:** Streamable HTTP
- **Auth:** OAuth 2.1 — sign in with your SV account; your API key stays on the server
- **Docs:** https://seovendor.co/api/mcp
- **Free API key:** https://access.seovendor.co/signup

## Connect

### Claude.ai and Claude Desktop

1. Open **Customize → Connectors**.
2. Click **+ → Add custom connector**.
3. Paste `https://mcp.seovendor.co` and click **Add**.
4. Click **Connect** and sign in to SV to approve access.

On Team and Enterprise plans, an Owner first adds the connector under **Organization settings → Connectors**; members then connect it themselves.

### Claude Code

```bash
claude mcp add --transport http sv-mcp https://mcp.seovendor.co
```

### Cursor (`~/.cursor/mcp.json`)

```json
{ "mcpServers": { "sv-mcp": { "url": "https://mcp.seovendor.co" } } }
```

### VS Code (`.vscode/mcp.json`)

```json
{ "servers": { "sv-mcp": { "type": "http", "url": "https://mcp.seovendor.co" } } }
```

### Windsurf (`~/.codeium/windsurf/mcp_config.json`)

```json
{ "mcpServers": { "sv-mcp": { "serverUrl": "https://mcp.seovendor.co" } } }
```

### Clients that only support stdio

```json
{ "mcpServers": { "sv-mcp": { "command": "npx", "args": ["-y", "mcp-remote", "https://mcp.seovendor.co"] } } }
```

## Tools

| Tool | What it does | Mode |
|---|---|---|
| `better-keywords` | Keyword research: search volume, CPC, competition and intent | Sync |
| `content-quality` | Scores a page's content quality (E-E-A-T) for a keyword | Sync |
| `content-transformer` | Rewrites or reformats supplied text into a content type | Sync |
| `core-analysis` | On-page SEO analysis of a URL | Sync |
| `insight-igniter` | Entities and topics AI engines associate with a website | Sync |
| `preliminaryaudit` | Quick automated SEO health score for a URL | Sync |
| `ranklens` | How a site ranks across repeated AI-engine queries, and competitors | Sync |
| `seogpt` | Short-form SEO text such as meta titles and descriptions | Sync |
| `topical-authority` | Topical content plan for a keyword | Sync |
| `top-competitors` | Top-ranking competitor URLs for a keyword | Sync |
| `marketplace-services` | Searches SV's catalog of purchasable services | Sync |
| `geogptaudit` | GEO audit: visibility in AI-generated answers for given entities | Async |
| `prose` | Writes a long-form article or blog post | Async |
| `seogptcompare` | Compares a URL against its top competitors for a keyword | Async |
| `seogptmapping` | Maps keywords to the most relevant pages on a domain | Async |
| `get_task_status` | Checks the status of an async task | — |
| `get_task_result` | Fetches the result of a finished async task | — |

**Async tools** return a `task_id` straight away; follow up with `get_task_status` / `get_task_result`, or pass `wait: true` to wait up to 45 seconds for the result in the same call.

**Points:** successful tool calls use points from your SV account. Failed calls, and checking on or fetching a task, don't.

**Rate limit:** the SV API accepts 1 request per second per API key. SV MCP retries automatically when it hits the limit, so this is normally invisible.

## Run locally (stdio)

For a single user on their own machine, run the server locally with your SV API key:

```bash
pip install sv-mcp
export SV_API_KEY=your-key
sv-mcp
```

Example client entry, using [uv](https://docs.astral.sh/uv/) so nothing needs installing first:

```json
{ "mcpServers": { "sv-mcp": { "command": "uvx", "args": ["sv-mcp"], "env": { "SV_API_KEY": "your-key" } } } }
```

## Hosted HTTP mode

`SV_MCP_TRANSPORT=http` runs the multi-user OAuth deployment behind `https://mcp.seovendor.co`. It authenticates against SV's own account system and needs an OAuth client secret registered there, so it is intended for SV's hosted deployment. See `.env.example` for the settings.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Privacy

See the SV privacy policy: https://seovendor.co/privacy-policy/

## Security

See [SECURITY.md](SECURITY.md). Report vulnerabilities to ask@seovendor.co.

## License

[MIT](LICENSE)
