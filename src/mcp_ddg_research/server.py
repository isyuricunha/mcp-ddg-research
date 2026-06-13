"""FastMCP server entrypoint."""

from __future__ import annotations

import logging
import os
from hmac import compare_digest
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from mcp_ddg_research import cache as cache_ops
from mcp_ddg_research.fetch import ddg_deep_search as perform_deep_search
from mcp_ddg_research.fetch import web_fetch as perform_web_fetch
from mcp_ddg_research.models import (
    ARGUMENT_DESCRIPTIONS,
    CacheNamespace,
    SafeSearch,
    TimeFilter,
)
from mcp_ddg_research.search import ddg_search as perform_ddg_search

LOGGER = logging.getLogger(__name__)

mcp = FastMCP(
    name="mcp-ddg-research",
    instructions=(
        "Deterministic DuckDuckGo search and safe webpage fetching tools. "
        "This server does not call LLMs, summarize, or generate reports."
    ),
)


class BearerTokenAuthMiddleware:
    """ASGI middleware that requires one configured bearer token."""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.expected_authorization = f"Bearer {token}"

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        authorization = _authorization_header(scope)
        if authorization is None or not compare_digest(
            authorization,
            self.expected_authorization,
        ):
            await _send_unauthorized(send)
            return

        await self.app(scope, receive, send)


def _authorization_header(scope: dict[str, Any]) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"authorization":
            return value.decode("latin-1")
    return None


async def _send_unauthorized(send: Any) -> None:
    body = b"Unauthorized"
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"www-authenticate", b"Bearer"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _csv_env(name: str, default: list[str]) -> list[str]:
    raw_value = os.getenv(name, "")
    values = [value.strip() for value in raw_value.split(",") if value.strip()]
    return values or default


def _has_wildcard(values: list[str]) -> bool:
    return "*" in values


def _http_auth_token() -> str | None:
    token = os.getenv("MCP_AUTH_TOKEN")
    if token is None or not token.strip():
        return None
    return token.strip()


def _build_transport_security_settings(
    allowed_hosts: list[str],
    allowed_origins: list[str],
) -> TransportSecuritySettings:
    wildcard_requested = _has_wildcard(allowed_hosts) or _has_wildcard(allowed_origins)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=not wildcard_requested,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def _configure_http_settings() -> None:
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))
    allowed_hosts = _csv_env("MCP_ALLOWED_HOSTS", ["*"])
    allowed_origins = _csv_env("MCP_ALLOWED_ORIGINS", ["*"])

    mcp.settings.host = host
    mcp.settings.port = port
    mcp.settings.transport_security = _build_transport_security_settings(
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


async def _run_http_async() -> None:
    import uvicorn

    auth_token = _http_auth_token()
    if auth_token is None:
        LOGGER.warning(
            "MCP HTTP transport is running without MCP_AUTH_TOKEN; "
            "all HTTP requests are unauthenticated."
        )

    starlette_app = mcp.streamable_http_app()
    if auth_token is not None:
        starlette_app.add_middleware(BearerTokenAuthMiddleware, token=auth_token)

    config = uvicorn.Config(
        starlette_app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


@mcp.tool()
async def ddg_search(
    query: Annotated[str, Field(min_length=1, description=ARGUMENT_DESCRIPTIONS["query"])],
    max_results: Annotated[
        int,
        Field(ge=1, le=30, description=ARGUMENT_DESCRIPTIONS["max_results"]),
    ] = 10,
    search_window: Annotated[
        int | None,
        Field(ge=1, le=100, description=ARGUMENT_DESCRIPTIONS["search_window"]),
    ] = None,
    safe_search: Annotated[
        SafeSearch,
        Field(description=ARGUMENT_DESCRIPTIONS["safe_search"]),
    ] = "off",
    time_filter: Annotated[
        TimeFilter | None,
        Field(description=ARGUMENT_DESCRIPTIONS["time_filter"]),
    ] = None,
    blocked_domains: Annotated[
        list[str] | None,
        Field(description=ARGUMENT_DESCRIPTIONS["blocked_domains"]),
    ] = None,
    allowed_domains: Annotated[
        list[str] | None,
        Field(description=ARGUMENT_DESCRIPTIONS["allowed_domains"]),
    ] = None,
    preferred_domains: Annotated[
        list[str] | None,
        Field(description=ARGUMENT_DESCRIPTIONS["preferred_domains"]),
    ] = None,
) -> dict:
    """Search DuckDuckGo using ddgs first, then the HTML fallback."""

    response = await perform_ddg_search(
        query=query,
        max_results=max_results,
        search_window=search_window,
        safe_search=safe_search,
        time_filter=time_filter,
        blocked_domains=blocked_domains,
        allowed_domains=allowed_domains,
        preferred_domains=preferred_domains,
    )
    return response.model_dump(mode="json")


@mcp.tool()
async def web_fetch(
    url: Annotated[str, Field(min_length=1, description=ARGUMENT_DESCRIPTIONS["url"])],
    max_chars: Annotated[
        int,
        Field(ge=1000, le=50000, description=ARGUMENT_DESCRIPTIONS["max_chars"]),
    ] = 12000,
) -> dict:
    """Fetch one HTTP(S) page safely and return extracted text."""

    response = await perform_web_fetch(url=url, max_chars=max_chars)
    return response.model_dump(mode="json")


@mcp.tool()
async def ddg_deep_search(
    query: Annotated[str, Field(min_length=1, description=ARGUMENT_DESCRIPTIONS["query"])],
    max_results: Annotated[
        int,
        Field(ge=1, le=30, description=ARGUMENT_DESCRIPTIONS["max_results"]),
    ] = 10,
    search_window: Annotated[
        int | None,
        Field(ge=1, le=100, description=ARGUMENT_DESCRIPTIONS["search_window"]),
    ] = None,
    max_pages: Annotated[
        int,
        Field(ge=1, le=10, description=ARGUMENT_DESCRIPTIONS["max_pages"]),
    ] = 5,
    max_chars_per_page: Annotated[
        int,
        Field(ge=1000, le=50000, description=ARGUMENT_DESCRIPTIONS["max_chars_per_page"]),
    ] = 12000,
    safe_search: Annotated[
        SafeSearch,
        Field(description=ARGUMENT_DESCRIPTIONS["safe_search"]),
    ] = "off",
    time_filter: Annotated[
        TimeFilter | None,
        Field(description=ARGUMENT_DESCRIPTIONS["time_filter"]),
    ] = None,
    blocked_domains: Annotated[
        list[str] | None,
        Field(description=ARGUMENT_DESCRIPTIONS["blocked_domains"]),
    ] = None,
    allowed_domains: Annotated[
        list[str] | None,
        Field(description=ARGUMENT_DESCRIPTIONS["allowed_domains"]),
    ] = None,
    preferred_domains: Annotated[
        list[str] | None,
        Field(description=ARGUMENT_DESCRIPTIONS["preferred_domains"]),
    ] = None,
    max_concurrency: Annotated[
        int | None,
        Field(ge=1, le=12, description=ARGUMENT_DESCRIPTIONS["max_concurrency"]),
    ] = None,
) -> dict:
    """Search once, fetch top pages in parallel, and return raw page text."""

    response = await perform_deep_search(
        query=query,
        max_results=max_results,
        search_window=search_window,
        max_pages=max_pages,
        max_chars_per_page=max_chars_per_page,
        safe_search=safe_search,
        time_filter=time_filter,
        blocked_domains=blocked_domains,
        allowed_domains=allowed_domains,
        preferred_domains=preferred_domains,
        max_concurrency=max_concurrency,
    )
    return response.model_dump(mode="json")


@mcp.tool()
async def cache_stats() -> dict:
    """Return cache file counts and byte totals for each cache namespace."""

    return cache_ops.get_cache_stats().to_dict()


@mcp.tool()
async def cache_prune(
    expired_only: Annotated[
        bool,
        Field(description=ARGUMENT_DESCRIPTIONS["expired_only"]),
    ] = False,
    dry_run: Annotated[
        bool,
        Field(description=ARGUMENT_DESCRIPTIONS["dry_run"]),
    ] = False,
) -> dict:
    """Prune expired, corrupt, temporary, and oversized cache files."""

    return cache_ops.prune_cache(expired_only=expired_only, dry_run=dry_run).to_dict()


@mcp.tool()
async def cache_clear(
    namespace: Annotated[
        CacheNamespace,
        Field(description=ARGUMENT_DESCRIPTIONS["namespace"]),
    ],
    confirm: Annotated[
        bool,
        Field(description=ARGUMENT_DESCRIPTIONS["confirm"]),
    ],
) -> dict:
    """Clear one cache namespace, or all namespaces, when confirm is true."""

    return cache_ops.clear_cache(namespace=namespace, confirm=confirm).to_dict()


def _prune_cache_on_startup() -> None:
    try:
        stats = cache_ops.prune_cache_on_startup()
    except Exception:  # noqa: BLE001 - cache pruning must not block server startup.
        LOGGER.warning("Startup cache pruning failed", exc_info=True)
        return
    if stats is not None and stats.deleted_files:
        LOGGER.info(
            "Pruned %s cache files on startup (%s bytes)",
            stats.deleted_files,
            stats.deleted_bytes,
        )


def main() -> None:
    _prune_cache_on_startup()
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "http":
        import asyncio

        _configure_http_settings()
        asyncio.run(_run_http_async())
        return

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
