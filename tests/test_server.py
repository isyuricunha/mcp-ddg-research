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


async def _call_middleware(middleware, headers):
    messages = []
    scope = {"type": "http", "method": "GET", "path": "/mcp", "headers": headers}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware(scope, receive, send)
    return messages
