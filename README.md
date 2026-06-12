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
  "time_filter": "month"
}
```

Argument rules:

- `query`: string, required.
- `max_results`: integer, default `10`, minimum `1`, maximum `30`.
- `safe_search`: one of `off`, `moderate`, `strict`, default `off`.
- `time_filter`: optional, one of `day`, `week`, `month`, `year`.

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
  "time_filter": "year"
}
```

Argument rules:

- `query`: string, required.
- `max_results`: integer, default `10`, minimum `1`, maximum `30`.
- `max_pages`: integer, default `5`, minimum `1`, maximum `10`.
- `max_chars_per_page`: integer, default `12000`, minimum `1000`, maximum `50000`.
- `safe_search`: one of `off`, `moderate`, `strict`, default `off`.
- `time_filter`: optional, one of `day`, `week`, `month`, `year`.

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

## Docker Build

Build the local image:

```bash
docker build -t mcp-ddg-research:local .
```

Run the server over stdio:

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

Build and start the service:

```bash
docker compose up --build ddg-research
```

For MCP stdio clients, direct `docker run -i` is usually simpler than compose because the client owns stdin/stdout.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `MCP_CACHE_DIR` | `/data/cache` | Directory for JSON cache files. |
| `DDG_CACHE_TTL_SECONDS` | `21600` | Search cache TTL in seconds. |
| `FETCH_CACHE_TTL_SECONDS` | `7200` | Web fetch cache TTL in seconds. |
| `DDG_TIMEOUT_SECONDS` | `15` | DuckDuckGo provider and fallback timeout in seconds. |
| `FETCH_TIMEOUT_SECONDS` | `15` | Web fetch timeout in seconds. |
| `MAX_CONCURRENCY` | `5` | Deep search page fetch concurrency limit. |
| `MCP_TRANSPORT` | `stdio` | MCP transport. `stdio` is the default. `http` uses streamable HTTP when supported by the installed SDK. |
| `MCP_HOST` | `0.0.0.0` | Host used for optional streamable HTTP mode. |
| `MCP_PORT` | `8000` | Port used for optional streamable HTTP mode. |

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
