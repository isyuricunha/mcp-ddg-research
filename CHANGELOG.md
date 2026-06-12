# Changelog

## v0.3.2

- Publish Docker images when a `v*` release tag is pushed, so manual release tags publish to Docker Hub and GitHub Container Registry.
- Keep semantic-release publishing for branch releases while supporting explicit milestone tags.

## v0.3.1

- Add GitHub Actions release automation for validation, semantic releases, and multi-architecture Docker image publishing.
- Publish release images to Docker Hub as `mcp-ddg-research` under the configured Docker Hub namespace and to GitHub Container Registry under the repository path.
- Correct package metadata to use `https://github.com/isyuricunha/mcp-ddg-research`.

## v0.3.0

- Add opt-in `blocked_domains`, `allowed_domains`, and `preferred_domains` controls for `ddg_search` and `ddg_deep_search`.
- Preserve DuckDuckGo result order by default, with no built-in source bias or domain blocklist.
- Add per-call `max_concurrency` for `ddg_deep_search`, capped at 12.

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
