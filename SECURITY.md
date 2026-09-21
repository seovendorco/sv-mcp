# Security Policy

## Reporting vulnerabilities

Please do not open public issues for security vulnerabilities. Report suspected vulnerabilities privately to **ask@seovendor.co**.

Include:

- Affected version, commit, or the hosted server URL
- Reproduction steps
- Impact
- Any suggested fix

## How credentials are handled

- **Hosted server (`https://mcp.seovendor.co`):** clients authenticate with OAuth. The user's SV API key is resolved on the server for each request and is never returned to the MCP client or the AI host. Resolved keys are cached in server memory for up to 5 minutes.
- **Local stdio mode:** the server reads the key from the `SV_API_KEY` environment variable of the process that launches it.

## API-key safety

- Never commit API keys, `.env` files, or OAuth client secrets.
- Do not paste real keys into issues, logs, screenshots, examples, or tests.
- Keep `SV_MCP_OAUTH_CLIENT_SECRET` in your process manager or secret store, not in the repository.

## Supported versions

Security fixes target the latest released version and the hosted server.
