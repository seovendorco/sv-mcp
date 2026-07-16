"""FastMCP entry point for sv-mcp.

Two modes, chosen by the SV_MCP_TRANSPORT environment variable:
- stdio (default): local, single-user - spawned directly by an MCP host
  (Claude Desktop/Code), authenticated via one SV_API_KEY environment
  variable. Unchanged behavior from Phases 1-3.
- http: hosted, multi-user - authenticates each request via OAuth against
  SEOB's existing login system, then resolves that specific caller's own
  SV API key per-request (see execution.py) instead of one fixed key for
  the whole process.

The http-mode auth wiring uses two off-the-shelf FastMCP classes rather than
hand-rolled OAuth handling - see plan.md's Phase B section for why:
OAuthProxy bridges MCP clients (which expect Dynamic Client Registration)
against SEOB's fixed-credential OAuth app, and IntrospectionTokenVerifier
validates each opaque token by calling SEOB's checktoken.php (RFC 7662),
with built-in caching.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from fastmcp import FastMCP
from fastmcp.server.auth.oauth_proxy.proxy import OAuthProxy
from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier
from sv_cli.definitions import DefinitionsManager

from .tasks import build_task_tools
from .tool_registry import build_tools

# SEOB's OAuth endpoints - not secrets, but the base URL now varies between a
# dev/staging SEOB deployment and production, so it's configurable via
# SEOB_BASE_URL rather than hardcoded. Defaults to production. Whichever SEOB
# this points at must have Phase A's changes deployed (authorization.php,
# token.php, checktoken.php) and the schema migration + sv-mcp client
# registration run against *that* deployment's own database - these are not
# automatically shared between a dev SEOB and production SEOB.
SEOB_BASE_URL = os.environ.get("SEOB_BASE_URL", "https://access.seovendor.co")
SEOB_AUTHORIZATION_URL = f"{SEOB_BASE_URL}/OAuth/authorization.php"
SEOB_TOKEN_URL = f"{SEOB_BASE_URL}/OAuth/token.php"
SEOB_INTROSPECTION_URL = f"{SEOB_BASE_URL}/OAuth/checktoken.php"
SV_MCP_CLIENT_ID = "sv-mcp"
# Must exactly match the redirect_uri already registered in SEOB's oauth_clients
# table. OAuthProxy's own default redirect_path is "/auth/callback", which does
# NOT match what was registered ("/oauth/callback") - passed explicitly below
# rather than silently relying on a default that would break the flow.
OAUTH_REDIRECT_PATH = "/oauth/callback"


def _build_auth_provider() -> OAuthProxy:
    client_secret = os.environ.get("SV_MCP_OAUTH_CLIENT_SECRET")
    if not client_secret:
        raise RuntimeError(
            "SV_MCP_OAUTH_CLIENT_SECRET is required when SV_MCP_TRANSPORT=http - this "
            "is the client_secret sv-mcp was registered with in SEOB's oauth_clients table."
        )
    base_url = os.environ.get("SV_MCP_BASE_URL", "https://mcp.seovendor.co")

    token_verifier = IntrospectionTokenVerifier(
        introspection_url=SEOB_INTROSPECTION_URL,
        client_id=SV_MCP_CLIENT_ID,
        client_secret=client_secret,
        # Real-time revocation matters less than reducing load on SEOB for a
        # 90-day-lived token; a short cache is a deliberate middle ground -
        # not the library's own default (no caching at all).
        cache_ttl_seconds=300,
    )
    return OAuthProxy(
        upstream_authorization_endpoint=SEOB_AUTHORIZATION_URL,
        upstream_token_endpoint=SEOB_TOKEN_URL,
        upstream_client_id=SV_MCP_CLIENT_ID,
        upstream_client_secret=client_secret,
        token_verifier=token_verifier,
        base_url=base_url,
        redirect_path=OAUTH_REDIRECT_PATH,
        # Left unset, authlib defaults to "client_secret_basic" (HTTP Basic Auth
        # header) whenever a client_secret is present - but token.php only ever
        # reads client_id/client_secret from the POST body, never checks the
        # Basic Auth header, so the default silently produced "invalid_client"
        # (empty credentials matched nothing in oauth_clients). Forced to match
        # what token.php actually implements.
        token_endpoint_auth_method="client_secret_post",
        # require_authorization_consent left at its default (True): shows a
        # distinct "sv-mcp wants access to your account" screen after SEOB's
        # own login - standard OAuth UX (same pattern as "Sign in with Google"
        # flows), and the library's own docs say this protects against
        # confused-deputy attacks. Not weakened for convenience.
    )


def create_server() -> FastMCP:
    transport_mode = os.environ.get("SV_MCP_TRANSPORT", "stdio")
    auth = _build_auth_provider() if transport_mode != "stdio" else None

    mcp = FastMCP(name="sv-mcp", auth=auth)
    definitions = DefinitionsManager()
    for tool in build_tools(definitions):
        mcp.add_tool(tool)
    for tool in build_task_tools():
        mcp.add_tool(tool)
    return mcp


def main() -> None:
    server = create_server()
    transport_mode = os.environ.get("SV_MCP_TRANSPORT", "stdio")

    if transport_mode == "stdio":
        server.run(transport="stdio", show_banner=False)
    else:
        host = os.environ.get("SV_MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("SV_MCP_PORT", "8080"))
        # FastMCP's HostOriginGuardMiddleware rejects any request whose Host header
        # isn't in DEFAULT_HOSTS ("127.0.0.1", "localhost", "::1") or explicitly
        # allowed here - a tunnel (ngrok, cloudflared) or a real public domain both
        # arrive with a Host header FastMCP has never seen before, so without this
        # every single request 421s before reaching any of sv-mcp's own routing or
        # auth logic. Derived from SV_MCP_BASE_URL (already required) rather than a
        # separate setting, so it's automatically correct for both a test tunnel and
        # the real mcp.seovendor.co domain later.
        public_host = urlparse(os.environ.get("SV_MCP_BASE_URL", "")).hostname
        allowed_hosts = [public_host] if public_host else None
        server.run(
            transport="http",
            host=host,
            port=port,
            show_banner=False,
            allowed_hosts=allowed_hosts,
            # FastMCP mounts the Streamable HTTP endpoint at /mcp by default. Moved
            # to the bare root so the connector URL end users type is just
            # SV_MCP_BASE_URL itself, with no suffix to remember or forget - the
            # OAuth routes (/authorize, /token, /register, /.well-known/...) are
            # separate, distinct paths and don't collide with this.
            path="/",
        )


if __name__ == "__main__":
    main()
