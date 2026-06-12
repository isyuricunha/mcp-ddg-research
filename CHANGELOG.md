# Changelog

## v0.2.1

- Polish HTTP MCP deployment documentation for stdio, LAN HTTP, OpenCode remote MCP, and HTTPS reverse proxy usage.
- Document bearer-token smoke-test responses, including why raw curl can return `406 Not Acceptable` while auth and Host handling are working.
- Replace user-specific HTTP examples with deployment placeholders.
- Align package metadata with the `v0.2.1` release.

## v0.2.0

- Add authenticated streamable HTTP MCP transport for remote clients.
- Support configurable HTTP bind host, port, bearer token, and Host/Origin deployment settings.
- Preserve stdio transport behavior for local Docker MCP clients.

## v0.1.0

- Initial Dockerized FastMCP server with DuckDuckGo search, HTML fallback, safe webpage fetching, JSON cache, URL safety checks, deduplication, and clean text extraction.
