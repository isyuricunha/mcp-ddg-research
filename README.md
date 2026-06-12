# mcp-ddg-research

Lightweight MCP server for DuckDuckGo search with HTML fallback, safe webpage fetching, caching, and clean text extraction.

`mcp-ddg-research` is a self-hosted Python MCP server that exposes deterministic research primitives to MCP clients. It can run DuckDuckGo searches, fall back to DuckDuckGo's lightweight HTML endpoint when the `ddgs` provider fails, fetch webpages with SSRF protections, cache search/fetch responses, deduplicate URLs, and extract readable text from HTML pages.

The MCP client or agent is responsible for reasoning over the returned data. This server only returns structured search results and fetched page text.

## What This Project Does

- Searches DuckDuckGo through `ddgs.DDGS().text(...)`.
- Falls back to `https://html.duckduckgo.com/html/` when `ddgs` fails, times out, rate limits, raises, or returns no results.
- Parses DuckDuckGo HTML fallback results with BeautifulSoup.
- Resolves DuckDuckGo redirect URLs such as `/l/?uddg=...`.
- Deduplicates normalized result URLs.
- Fetches webpages with strict URL and DNS safety checks.
- Follows redirects manually and validates every redirect target.
- Extracts clean text from HTML by removing script, style, navigation, footer, and similar boilerplate.
- Caches search and fetch responses in a file-based JSON cache.
- Provides a simple deep search tool that searches once and fetches top result pages concurrently.

## What This Project Does Not Do

- No LLM integration.
- No summarization.
- No report generation.
- No browser automation.
- No proxy rotation.
- No captcha bypassing.
- No ranking with model endpoints.
- No OpenAI, Anthropic, Ollama, LM Studio, or other model endpoint support.

## Why HTML Fallback Exists

The `ddgs` package is the preferred provider because it offers a simple Python API and handles DuckDuckGo search details for normal use. Search providers can still fail because of network timeouts, temporary provider errors, rate limits, empty responses, dependency import problems, or upstream behavior changes.

When that happens, this server falls back to DuckDuckGo's lightweight HTML endpoint. The fallback uses conservative request defaults, browser-like headers, and BeautifulSoup selectors for `.result`, `.result__a`, and `.result__snippet`.

## Available MCP Tools

### `ddg_search`

Search DuckDuckGo and return structured results.

Arguments:

```json
{
  "query": "python mcp server fastmcp",
  "max_results": 10,
  "safe_search": "off",
  "time_filter": "month",
  "blocked_domains": [],
  "allowed_domains": [],
  "preferred_domains": []
}
```

Argument rules:

- `query`: string, required.
- `max_results`: integer, default `10`, minimum `1`, maximum `30`.
- `safe_search`: one of `off`, `moderate`, `strict`, default `off`.
- `time_filter`: optional, one of `day`, `week`, `month`, `year`.
- `blocked_domains`: optional list of domains to remove from results, default `[]`.
- `allowed_domains`: optional list of domains to keep, default `[]`.
- `preferred_domains`: optional list of domains to move earlier while preserving stable order, default `[]`.

Response example:

```json
{
  "query": "python mcp server fastmcp",
  "provider": "ddgs",
  "results": [
    {
      "title": "MCP Python SDK",
      "url": "https://github.com/modelcontextprotocol/python-sdk",
      "snippet": "Python SDK for Model Context Protocol servers and clients."
    }
  ],
  "cached": false,
  "error": null
}
```

### `web_fetch`

Fetch a single webpage and return clean text.

Arguments:

```json
{
  "url": "https://example.com/article",
  "max_chars": 12000
}
```

Argument rules:

- `url`: HTTP or HTTPS URL.
- `max_chars`: integer, default `12000`, minimum `1000`, maximum `50000`.

Response example:

```json
{
  "url": "https://example.com/article",
  "final_url": "https://example.com/article",
  "title": "Example Article",
  "content": "Readable extracted page text...",
  "content_type": "text/html; charset=utf-8",
  "cached": false,
  "success": true,
  "error": null
}
```

### `ddg_deep_search`

Search once, fetch top result pages concurrently, and return sources plus page content.

Arguments:

```json
{
  "query": "model context protocol python sdk",
  "max_results": 10,
  "max_pages": 5,
  "max_chars_per_page": 12000,
  "safe_search": "off",
  "time_filter": "year",
  "blocked_domains": [],
  "allowed_domains": [],
  "preferred_domains": [],
  "max_concurrency": null
}
```

Argument rules:

- `query`: string, required.
- `max_results`: integer, default `10`, minimum `1`, maximum `30`.
- `max_pages`: integer, default `5`, minimum `1`, maximum `10`.
- `max_chars_per_page`: integer, default `12000`, minimum `1000`, maximum `50000`.
- `safe_search`: one of `off`, `moderate`, `strict`, default `off`.
- `time_filter`: optional, one of `day`, `week`, `month`, `year`.
- `blocked_domains`: optional list of domains to remove from search results before fetching, default `[]`.
- `allowed_domains`: optional list of domains to keep before fetching, default `[]`.
- `preferred_domains`: optional list of domains to move earlier before fetching, default `[]`.
- `max_concurrency`: optional per-call page fetch concurrency, minimum `1`, maximum `12`. If omitted, `MAX_CONCURRENCY` is used.

Response example:

```json
{
  "query": "model context protocol python sdk",
  "search_provider": "ddgs",
  "sources": [
    {
      "title": "MCP Python SDK",
      "url": "https://github.com/modelcontextprotocol/python-sdk",
      "snippet": "Python SDK for Model Context Protocol servers and clients."
    }
  ],
  "pages": [
    {
      "title": "MCP Python SDK",
      "url": "https://github.com/modelcontextprotocol/python-sdk",
      "final_url": "https://github.com/modelcontextprotocol/python-sdk",
      "content": "Extracted page text..."
    }
  ],
  "failed_pages": [],
  "cached": false
}
```

## Domain Controls

Domain controls are opt-in. If you do not pass `blocked_domains`,
`allowed_domains`, or `preferred_domains`, search results preserve DuckDuckGo's
default ranking order after URL deduplication. The server does not apply a
built-in source bias, source boost, or domain blocklist.

Domain inputs are normalized by lowercasing, removing URL schemes, removing
paths and query strings, and stripping a leading `www.`. Matching supports exact
domains and subdomains. For example, `docs.example.com` matches `example.com`,
but `example.com.evil.com` does not.

Filtering order:

1. Apply `allowed_domains` if provided.
2. Apply `blocked_domains` if provided.
3. Apply `preferred_domains` if provided.

`preferred_domains` performs a stable partition: preferred matches move earlier,
relative order is preserved inside the preferred and non-preferred groups, and
no numeric score is invented.

Block domains:

```json
{
  "query": "self hosted photo backup",
  "blocked_domains": ["example.com", "old-docs.example.org"]
}
```

Allow only specific domains:

```json
{
  "query": "python mcp server",
  "allowed_domains": ["github.com", "modelcontextprotocol.io"]
}
```

Prefer domains without excluding others:

```json
{
  "query": "duckduckgo html search endpoint",
  "preferred_domains": ["duckduckgo.com", "github.com"]
}
```

Limit deep-search fetch concurrency for one call:

```json
{
  "query": "model context protocol python sdk",
  "max_pages": 5,
  "max_concurrency": 2
}
```

## Docker Stdio Usage

Build the local image:

```bash
docker build -t mcp-ddg-research:local .
```

Run the server over stdio. This mode is auth-free because the MCP client owns
stdin/stdout and there is no listening network socket:

```bash
docker run --rm -i -v "$PWD/data:/data" mcp-ddg-research:local
```

## Docker Stdio MCP Client Configuration

```json
{
  "mcpServers": {
    "ddg-research": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-v",
        "/opt/mcp-ddg-research/data:/data",
        "mcp-ddg-research:local"
      ]
    }
  }
}
```

## docker-compose Usage

The included compose file starts the server in streamable HTTP mode on `/mcp`.
It exposes port `8000` and requires `Authorization: Bearer <token>` when
`MCP_AUTH_TOKEN` is set.

Build and start the service:

```bash
export MCP_AUTH_TOKEN="replace-with-a-long-random-token"
docker compose up --build ddg-research
```

If `MCP_AUTH_TOKEN` is not exported, compose uses the local placeholder token
`change-me`. That is acceptable for a quick local smoke test only. Replace it
before using LAN, VPN, or reverse-proxy deployments.

The compose file defaults `MCP_ALLOWED_HOSTS=*` and `MCP_ALLOWED_ORIGINS=*` so
the same container can run behind a LAN IP, hostname, domain, reverse proxy, or
HTTPS endpoint. In MCP SDK `1.27.2`, wildcard Host/Origin validation is not
supported by the DNS rebinding middleware, so wildcard mode disables the SDK
Host/Origin allowlist and relies on the bearer token. To enable strict
Host/Origin checks, set exact comma-separated values such as:

```bash
MCP_ALLOWED_HOSTS="example.com,example.com:443,localhost:8000"
MCP_ALLOWED_ORIGINS="https://example.com,http://localhost:*"
```

### LAN HTTP Example

Set a real token and start the server:

```bash
export MCP_AUTH_TOKEN="replace-with-a-long-random-token"
docker compose up -d --build
```

Use your server's LAN IP in the client URL:

```text
http://YOUR_SERVER_IP:8000/mcp
```

OpenCode remote MCP configuration for a LAN deployment:

```json
{
  "mcp": {
    "ddg-research": {
      "type": "remote",
      "enabled": true,
      "url": "http://YOUR_SERVER_IP:8000/mcp",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer replace-with-a-long-random-token"
      }
    }
  }
}
```

### HTTPS Reverse Proxy Example

Run the container on the server and terminate TLS in a reverse proxy. The proxy
should forward `/mcp` to `http://127.0.0.1:8000/mcp` and preserve standard
upgrade/streaming behavior.

Minimal Nginx-style location:

```nginx
location /mcp {
    proxy_pass http://127.0.0.1:8000/mcp;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;
}
```

OpenCode configuration for the HTTPS endpoint:

```json
{
  "mcp": {
    "ddg-research": {
      "type": "remote",
      "enabled": true,
      "url": "https://your-domain.example/mcp",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer replace-with-a-long-random-token"
      }
    }
  }
}
```

Do not expose HTTP mode to an untrusted network without HTTPS and a strong
`MCP_AUTH_TOKEN`. If `MCP_AUTH_TOKEN` is unset in HTTP mode, the server logs a
warning and accepts unauthenticated HTTP requests.

For MCP stdio clients, direct `docker run -i` is usually simpler than compose because the client owns stdin/stdout.

## HTTP Smoke Tests

Raw `curl` is useful for checking HTTP authentication and Host handling, but it
does not perform a complete MCP streamable HTTP session. A request with the
correct bearer token may therefore return `406 Not Acceptable` because curl did
not send the MCP client's expected `Accept: text/event-stream` negotiation
headers. That still proves the request passed bearer-token auth and Host
validation.

With the compose server running and `MCP_AUTH_TOKEN=replace-with-a-long-random-token`:

```bash
curl -i http://127.0.0.1:8000/mcp
```

Expected: `401 Unauthorized`.

```bash
curl -i \
  -H "Host: YOUR_SERVER_IP:8000" \
  -H "Authorization: Bearer replace-with-a-long-random-token" \
  http://127.0.0.1:8000/mcp
```

Expected: usually `406 Not Acceptable` from raw curl, but not `401 Unauthorized`
and not `421 Misdirected Request`.

With a real MCP client, such as OpenCode configured with the same URL and
Authorization header, `ListTools` and `CallTool` should work for `ddg_search`,
`web_fetch`, and `ddg_deep_search`.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `MCP_CACHE_DIR` | `/data/cache` | Directory for JSON cache files. |
| `DDG_CACHE_TTL_SECONDS` | `21600` | Search cache TTL in seconds. |
| `FETCH_CACHE_TTL_SECONDS` | `7200` | Web fetch cache TTL in seconds. |
| `DDG_TIMEOUT_SECONDS` | `15` | DuckDuckGo provider and fallback timeout in seconds. |
| `FETCH_TIMEOUT_SECONDS` | `15` | Web fetch timeout in seconds. |
| `MAX_CONCURRENCY` | `5` | Default deep search page fetch concurrency limit when `max_concurrency` is omitted. Runtime caps this at `12`. |
| `MCP_TRANSPORT` | `stdio` | MCP transport. `stdio` is the default. `http` uses streamable HTTP when supported by the installed SDK. |
| `MCP_HOST` | `0.0.0.0` | Host used for optional streamable HTTP mode. |
| `MCP_PORT` | `8000` | Port used for optional streamable HTTP mode. |
| `MCP_AUTH_TOKEN` | unset | Bearer token for HTTP mode. If set, every HTTP request must send `Authorization: Bearer <token>`. If unset, HTTP mode logs a warning and runs without auth. |
| `MCP_ALLOWED_HOSTS` | `*` | Comma-separated Host allowlist for HTTP mode. `*` supports arbitrary deployment hosts by disabling SDK Host/Origin rebinding checks. |
| `MCP_ALLOWED_ORIGINS` | `*` | Comma-separated Origin allowlist for HTTP mode. `*` supports arbitrary origins by disabling SDK Host/Origin rebinding checks. |

## Cache Behavior

Search results are cached under the `search` cache namespace. Fetch responses are cached under the `fetch` cache namespace. Cache keys are SHA256 hashes of stable JSON payloads, so equivalent tool arguments map to the same file path.

Cache files are written atomically by writing a temporary file in the target cache directory and then renaming it into place. Corrupt, malformed, or expired cache files are ignored safely.

The default Docker configuration persists cache files in `/data/cache`, with `./data` mounted into the container.

## Rate Limit Notes

Defaults are intentionally conservative:

- `ddg_search` defaults to 10 results and caps at 30.
- `ddg_deep_search` defaults to 5 fetched pages and caps at 10.
- Deep search concurrency defaults to 5.
- Search and fetch results are cached to reduce repeated DuckDuckGo and website hits.

This project does not rotate proxies, bypass captchas, or attempt to evade rate limits. If DuckDuckGo blocks or rate limits requests, the tool returns structured errors instead of retrying aggressively.

## SSRF and Security Protections

`web_fetch` only allows `http` and `https` URLs. It blocks known local or internal hostnames, including:

- `localhost`
- `metadata`
- `metadata.google.internal`
- hostnames ending in `.local`, `.localhost`, `.internal`, `.lan`, `.intranet`

It also rejects IP addresses in private, loopback, link-local, reserved, multicast, or unspecified ranges, including:

- `0.0.0.0/8`
- `10.0.0.0/8`
- `127.0.0.0/8`
- `169.254.0.0/16`
- `172.16.0.0/12`
- `192.168.0.0/16`
- `::1/128`
- `fc00::/7`
- `fe80::/10`

DNS is resolved before fetching. If any resolved address is unsafe, the request is rejected. Redirects are followed manually, and every redirect target is validated before the next request.

Unsupported schemes such as `file://`, `ftp://`, `ssh://`, `gopher://`, and `data:` are never fetched.

## Development Setup

Python 3.12 is required.

Create and activate a virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Install the package with development tools:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the MCP server locally:

```bash
python -m mcp_ddg_research.server
```

## Test Commands

Run tests:

```bash
python -m pytest
```

Run lint:

```bash
python -m ruff check .
```

Build a wheel/sdist using the configured build backend:

```bash
python -m pip install build
python -m build
```

## Release Automation

Releases are automated by `.github/workflows/release.yml` when commits are
pushed to `main`. The workflow is Python-native:

1. Install the project with development dependencies.
2. Run Ruff, pytest, compile checks, Python package build, and a Docker build.
3. Use Python Semantic Release to create the next GitHub release from
   conventional commits.
4. If a release is created, build and push multi-architecture Docker images for
   `linux/amd64` and `linux/arm64`.

The workflow publishes these image tags:

```text
DOCKERHUB_USERNAME/mcp-ddg-research:latest
DOCKERHUB_USERNAME/mcp-ddg-research:vX.Y.Z
ghcr.io/isyuricunha/mcp-ddg-research:latest
ghcr.io/isyuricunha/mcp-ddg-research:vX.Y.Z
```

Required repository secrets:

| Secret | Purpose |
| --- | --- |
| `DOCKERHUB_USERNAME` | Docker Hub namespace for the published image. |
| `DOCKERHUB_TOKEN` | Docker Hub access token used by `docker/login-action`. |
| `GITHUB_TOKEN` | Provided automatically by GitHub Actions for GitHub releases and GHCR publishing. |

Use conventional commits to drive release versions:

- `fix: ...` and `perf: ...` create patch releases.
- `feat: ...` creates minor releases while the project is in `0.x`.
- Breaking changes are capped to a minor release while the project is in `0.x`;
  after `1.0.0`, they create major releases.
- `docs:`, `ci:`, `chore:`, `test:`, `style:`, and `refactor:` do not create a
  release by default.

The release workflow updates `pyproject.toml`, `src/mcp_ddg_research/__init__.py`,
and `CHANGELOG.md` during the release commit. It is intentionally skipped for
documentation-only pushes and compose-file-only pushes.

## Limitations

- DuckDuckGo HTML fallback does not support every option exposed by DuckDuckGo's full web interface.
- `time_filter` is applied to the `ddgs` provider. The HTML fallback only sends the query and safe-search parameter.
- PDF parsing is not implemented in v1.
- JavaScript-rendered pages are not rendered because there is no browser automation.
- Some websites block automated HTTP clients or return incomplete content.
- DNS safety checks reduce SSRF risk but cannot make arbitrary third-party fetching risk-free.

## Optional Future Roadmap

These are optional future improvements, not current behavior:

- Add configurable per-domain fetch throttling.
- Add cache pruning utilities.
- Add optional robots.txt awareness.
- Add additional text extraction heuristics for common article layouts.
- Add more integration tests around redirect chains and text content types.
