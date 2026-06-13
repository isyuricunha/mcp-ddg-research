import asyncio

from mcp_ddg_research.server import (
    BearerTokenAuthMiddleware,
    _build_transport_security_settings,
    _configure_http_settings,
    mcp,
)


def test_configure_http_settings_defaults_to_wildcard_hosts(monkeypatch) -> None:
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_PORT", "8000")
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)

    _configure_http_settings()

    assert mcp.settings.host == "0.0.0.0"
    assert mcp.settings.port == 8000
    assert mcp.settings.transport_security is not None
    assert mcp.settings.transport_security.enable_dns_rebinding_protection is False
    assert mcp.settings.transport_security.allowed_hosts == ["*"]
    assert mcp.settings.transport_security.allowed_origins == ["*"]


def test_explicit_hosts_keep_dns_rebinding_protection_enabled() -> None:
    settings = _build_transport_security_settings(
        allowed_hosts=["example.com", "example.com:443"],
        allowed_origins=["https://example.com"],
    )

    assert settings.enable_dns_rebinding_protection is True
    assert settings.allowed_hosts == ["example.com", "example.com:443"]
    assert settings.allowed_origins == ["https://example.com"]


def test_bearer_token_middleware_rejects_missing_authorization() -> None:
    called = False

    async def app(scope, receive, send) -> None:
        nonlocal called
        called = True

    middleware = BearerTokenAuthMiddleware(app, token="secret")
    messages = asyncio.run(_call_middleware(middleware, headers=[]))

    assert called is False
    assert messages[0]["status"] == 401
    assert (b"www-authenticate", b"Bearer") in messages[0]["headers"]


def test_bearer_token_middleware_accepts_valid_authorization() -> None:
    called = False

    async def app(scope, receive, send) -> None:
        nonlocal called
        called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = BearerTokenAuthMiddleware(app, token="secret")
    messages = asyncio.run(
        _call_middleware(
            middleware,
            headers=[(b"authorization", b"Bearer secret")],
        )
    )

    assert called is True
    assert messages[0]["status"] == 200


def test_tool_schema_describes_search_window_as_result_count() -> None:
    schemas = asyncio.run(_tool_schemas_by_name())

    search_window = schemas["ddg_search"]["properties"]["search_window"]
    deep_search_window = schemas["ddg_deep_search"]["properties"]["search_window"]

    assert "Internal provider result count" in search_window["description"]
    assert "not a time range or number of days" in search_window["description"]
    assert deep_search_window["description"] == search_window["description"]


def test_tool_schema_describes_domain_controls() -> None:
    schemas = asyncio.run(_tool_schemas_by_name())
    properties = schemas["ddg_search"]["properties"]

    assert "Exclusive domain allowlist" in properties["allowed_domains"]["description"]
    assert "Exclusion list" in properties["blocked_domains"]["description"]
    assert "not exclusive filtering" in properties["preferred_domains"]["description"]


def test_tool_schema_describes_deep_search_fetch_controls() -> None:
    schemas = asyncio.run(_tool_schemas_by_name())
    properties = schemas["ddg_deep_search"]["properties"]

    assert "Number of top search result pages" in properties["max_pages"]["description"]
    assert "Per-call concurrent page fetch limit" in properties["max_concurrency"]["description"]


async def _tool_schemas_by_name() -> dict:
    tools = await mcp.list_tools()
    return {tool.name: tool.inputSchema for tool in tools}


async def _call_middleware(middleware, headers):
    messages = []
    scope = {"type": "http", "method": "GET", "path": "/mcp", "headers": headers}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware(scope, receive, send)
    return messages
