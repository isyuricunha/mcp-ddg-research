"""FastMCP server entrypoint."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from mcp_ddg_research.fetch import ddg_deep_search as perform_deep_search
from mcp_ddg_research.fetch import web_fetch as perform_web_fetch
from mcp_ddg_research.search import ddg_search as perform_ddg_search

mcp = FastMCP(
    name="mcp-ddg-research",
    instructions=(
        "Deterministic DuckDuckGo search and safe webpage fetching tools. "
        "This server does not call LLMs, summarize, or generate reports."
    ),
)


@mcp.tool()
async def ddg_search(
    query: str,
    max_results: int = 10,
    safe_search: str = "off",
    time_filter: str | None = None,
) -> dict:
    """Search DuckDuckGo using ddgs first, then the HTML fallback."""

    response = await perform_ddg_search(
        query=query,
        max_results=max_results,
        safe_search=safe_search,
        time_filter=time_filter,
    )
    return response.model_dump(mode="json")


@mcp.tool()
async def web_fetch(url: str, max_chars: int = 12000) -> dict:
    """Fetch one HTTP(S) page safely and return extracted text."""

    response = await perform_web_fetch(url=url, max_chars=max_chars)
    return response.model_dump(mode="json")


@mcp.tool()
async def ddg_deep_search(
    query: str,
    max_results: int = 10,
    max_pages: int = 5,
    max_chars_per_page: int = 12000,
    safe_search: str = "off",
    time_filter: str | None = None,
) -> dict:
    """Search once, fetch top pages in parallel, and return raw page text."""

    response = await perform_deep_search(
        query=query,
        max_results=max_results,
        max_pages=max_pages,
        max_chars_per_page=max_chars_per_page,
        safe_search=safe_search,
        time_filter=time_filter,
    )
    return response.model_dump(mode="json")


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "http":
        mcp.settings.host = os.getenv("MCP_HOST", "0.0.0.0")
        mcp.settings.port = int(os.getenv("MCP_PORT", "8000"))
        mcp.run(transport="streamable-http")
        return

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
