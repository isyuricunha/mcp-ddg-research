import asyncio
import builtins
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import mcp_ddg_research.search as search_module
from mcp_ddg_research.cache import JsonFileCache
from mcp_ddg_research.fetch import ddg_deep_search, get_max_concurrency
from mcp_ddg_research.models import (
    DeepSearchRequest,
    FetchRequest,
    FetchResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from mcp_ddg_research.search import (
    _search_with_ddgs,
    ddg_search,
    get_ddgs_backend,
    get_search_provider,
    parse_duckduckgo_html_results,
    provider_request_size,
    resolve_duckduckgo_redirect_url,
)


def test_redirect_resolver_resolves_duckduckgo_redirect() -> None:
    url = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com"

    assert resolve_duckduckgo_redirect_url(url) == "https://example.com"


def test_redirect_resolver_does_not_resolve_lookalike_host() -> None:
    url = "https://duckduckgo.com.evil.com/l/?uddg=https%3A%2F%2Fexample.com"

    assert resolve_duckduckgo_redirect_url(url) == url


def test_html_parser_parses_duckduckgo_result_snippet() -> None:
    html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs">
            Example Docs
          </a>
          <a class="result__snippet">Useful documentation snippet.</a>
        </div>
      </body>
    </html>
    """

    results = parse_duckduckgo_html_results(html, max_results=10)

    assert len(results) == 1
    assert results[0].title == "Example Docs"
    assert results[0].url == "https://example.com/docs"
    assert results[0].snippet == "Useful documentation snippet."


def test_search_request_rejects_invalid_max_results() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="example", max_results=31)


def test_search_request_rejects_invalid_search_window() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="example", search_window=101)


def test_search_request_rejects_invalid_safe_search() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="example", safe_search="disabled")


def test_request_models_include_argument_descriptions() -> None:
    search_schema = SearchRequest.model_json_schema()
    fetch_schema = FetchRequest.model_json_schema()
    deep_search_schema = DeepSearchRequest.model_json_schema()

    assert (
        "not a time range or number of days"
        in search_schema["properties"]["search_window"]["description"]
    )
    assert "SSRF protections" in fetch_schema["properties"]["url"]["description"]
    assert (
        "Per-call concurrent page fetch limit"
        in deep_search_schema["properties"]["max_concurrency"]["description"]
    )


def test_deep_search_request_accepts_max_concurrency() -> None:
    request = DeepSearchRequest(query="example", max_concurrency=12)

    assert request.max_concurrency == 12


def test_deep_search_request_accepts_search_window() -> None:
    request = DeepSearchRequest(query="example", search_window=100)

    assert request.search_window == 100


def test_deep_search_request_rejects_invalid_max_concurrency() -> None:
    with pytest.raises(ValidationError):
        DeepSearchRequest(query="example", max_concurrency=13)


def test_deep_search_request_rejects_invalid_search_window() -> None:
    with pytest.raises(ValidationError):
        DeepSearchRequest(query="example", search_window=101)


def test_get_max_concurrency_uses_per_call_value() -> None:
    assert get_max_concurrency(max_concurrency=3) == 3


def test_default_provider_is_duckduckgo_html(monkeypatch) -> None:
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)

    assert get_search_provider() == "duckduckgo_html"


def test_duckduckgo_html_provider_does_not_import_or_call_ddgs(monkeypatch, tmp_path) -> None:
    async def fake_html(request, timeout_seconds):
        return [_search_result("DuckDuckGo HTML", "https://example.com")]

    def fail_ddgs(*args, **kwargs):
        raise AssertionError("ddgs should not be called in duckduckgo_html mode")

    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ddgs" or name.startswith("ddgs."):
            raise AssertionError("ddgs should not be imported in duckduckgo_html mode")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setenv("SEARCH_PROVIDER", "duckduckgo_html")
    monkeypatch.setattr(search_module, "_search_with_duckduckgo_html", fake_html)
    monkeypatch.setattr(search_module, "_search_with_ddgs", fail_ddgs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)

    response = asyncio.run(
        ddg_search(
            query="example",
            cache=JsonFileCache(tmp_path, "search", ttl_seconds=60),
        )
    )

    assert response.provider == "duckduckgo_html"
    assert [result.title for result in response.results] == ["DuckDuckGo HTML"]


def test_ddgs_provider_calls_ddgs(monkeypatch, tmp_path) -> None:
    requested_backends: list[str] = []
    _install_fake_ddgs(monkeypatch, requested_sizes=[], requested_backends=requested_backends)

    async def fail_html(*args, **kwargs):
        raise AssertionError("duckduckgo_html should not be called in ddgs mode")

    monkeypatch.setenv("SEARCH_PROVIDER", "ddgs")
    monkeypatch.setenv("DDGS_BACKEND", "duckduckgo")
    monkeypatch.setattr(search_module, "_search_with_duckduckgo_html", fail_html)

    response = asyncio.run(
        ddg_search(
            query="example",
            cache=JsonFileCache(tmp_path, "search", ttl_seconds=60),
        )
    )

    assert response.provider == "ddgs"
    assert requested_backends == ["duckduckgo"]


def test_auto_provider_tries_duckduckgo_html_first(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    async def fake_html(request, timeout_seconds):
        calls.append("html")
        return [_search_result("HTML", "https://example.com")]

    def fail_ddgs(*args, **kwargs):
        raise AssertionError("ddgs should not run when duckduckgo_html returns results")

    monkeypatch.setenv("SEARCH_PROVIDER", "auto")
    monkeypatch.setattr(search_module, "_search_with_duckduckgo_html", fake_html)
    monkeypatch.setattr(search_module, "_search_with_ddgs", fail_ddgs)

    response = asyncio.run(
        ddg_search(
            query="example",
            cache=JsonFileCache(tmp_path, "search", ttl_seconds=60),
        )
    )

    assert response.provider == "duckduckgo_html"
    assert calls == ["html"]


def test_auto_provider_falls_back_to_ddgs_when_html_returns_no_results(
    monkeypatch,
    tmp_path,
) -> None:
    requested_backends: list[str] = []
    _install_fake_ddgs(monkeypatch, requested_sizes=[], requested_backends=requested_backends)

    async def empty_html(request, timeout_seconds):
        return []

    monkeypatch.setenv("SEARCH_PROVIDER", "auto")
    monkeypatch.setenv("DDGS_BACKEND", "duckduckgo")
    monkeypatch.setattr(search_module, "_search_with_duckduckgo_html", empty_html)

    response = asyncio.run(
        ddg_search(
            query="example",
            cache=JsonFileCache(tmp_path, "search", ttl_seconds=60),
        )
    )

    assert response.provider == "ddgs"
    assert requested_backends == ["duckduckgo"]


def test_auto_provider_falls_back_to_ddgs_when_html_fails(monkeypatch, tmp_path) -> None:
    requested_backends: list[str] = []
    _install_fake_ddgs(monkeypatch, requested_sizes=[], requested_backends=requested_backends)

    async def failing_html(request, timeout_seconds):
        raise RuntimeError("html failed")

    monkeypatch.setenv("SEARCH_PROVIDER", "auto")
    monkeypatch.setenv("DDGS_BACKEND", "duckduckgo")
    monkeypatch.setattr(search_module, "_search_with_duckduckgo_html", failing_html)

    response = asyncio.run(
        ddg_search(
            query="example",
            cache=JsonFileCache(tmp_path, "search", ttl_seconds=60),
        )
    )

    assert response.provider == "ddgs"
    assert requested_backends == ["duckduckgo"]


def test_invalid_provider_falls_back_to_duckduckgo_html(monkeypatch, tmp_path) -> None:
    async def fake_html(request, timeout_seconds):
        return [_search_result("HTML", "https://example.com")]

    monkeypatch.setenv("SEARCH_PROVIDER", "invalid")
    monkeypatch.setattr(search_module, "_search_with_duckduckgo_html", fake_html)

    response = asyncio.run(
        ddg_search(
            query="example",
            cache=JsonFileCache(tmp_path, "search", ttl_seconds=60),
        )
    )

    assert response.provider == "duckduckgo_html"


def test_ddgs_backend_duckduckgo_is_passed_when_supported(monkeypatch) -> None:
    requested_backends: list[str] = []
    _install_fake_ddgs(monkeypatch, requested_sizes=[], requested_backends=requested_backends)

    _search_with_ddgs(
        SearchRequest(query="example", max_results=4),
        timeout_seconds=15,
        backend="duckduckgo",
    )

    assert requested_backends == ["duckduckgo"]


def test_ddgs_backend_auto_is_passed_when_supported(monkeypatch) -> None:
    requested_backends: list[str] = []
    _install_fake_ddgs(monkeypatch, requested_sizes=[], requested_backends=requested_backends)

    _search_with_ddgs(
        SearchRequest(query="example", max_results=4),
        timeout_seconds=15,
        backend="auto",
    )

    assert requested_backends == ["auto"]


def test_invalid_ddgs_backend_falls_back_to_duckduckgo(monkeypatch) -> None:
    monkeypatch.setenv("DDGS_BACKEND", "not-real")
    monkeypatch.setattr(
        search_module,
        "_available_ddgs_text_backends",
        lambda: {"duckduckgo", "brave"},
    )

    assert get_ddgs_backend() == "duckduckgo"


def test_domain_controls_work_with_duckduckgo_html(monkeypatch, tmp_path) -> None:
    async def fake_html(request, timeout_seconds):
        return [
            _search_result("Blocked", "https://blocked.example/page"),
            _search_result("Allowed", "https://allowed.example/page"),
        ]

    monkeypatch.setenv("SEARCH_PROVIDER", "duckduckgo_html")
    monkeypatch.setattr(search_module, "_search_with_duckduckgo_html", fake_html)

    response = asyncio.run(
        ddg_search(
            query="example",
            allowed_domains=["allowed.example"],
            cache=JsonFileCache(tmp_path, "search", ttl_seconds=60),
        )
    )

    assert [result.title for result in response.results] == ["Allowed"]


def test_search_window_works_with_duckduckgo_html(monkeypatch, tmp_path) -> None:
    requested_sizes: list[int] = []

    async def fake_html(request, timeout_seconds):
        requested_sizes.append(provider_request_size(request))
        return [
            _search_result(f"Result {index}", f"https://example.com/{index}")
            for index in range(9)
        ]

    monkeypatch.setenv("SEARCH_PROVIDER", "duckduckgo_html")
    monkeypatch.setattr(search_module, "_search_with_duckduckgo_html", fake_html)

    response = asyncio.run(
        ddg_search(
            query="example",
            max_results=2,
            search_window=9,
            cache=JsonFileCache(tmp_path, "search", ttl_seconds=60),
        )
    )

    assert requested_sizes == [9]
    assert len(response.results) == 2


def test_search_cache_works_with_selected_provider(monkeypatch, tmp_path) -> None:
    calls = 0

    async def fake_html(request, timeout_seconds):
        nonlocal calls
        calls += 1
        return [_search_result("Cached", "https://example.com")]

    cache = JsonFileCache(tmp_path, "search", ttl_seconds=60)
    monkeypatch.setenv("SEARCH_PROVIDER", "duckduckgo_html")
    monkeypatch.setattr(search_module, "_search_with_duckduckgo_html", fake_html)

    first = asyncio.run(ddg_search(query="example", cache=cache))
    second = asyncio.run(ddg_search(query="example", cache=cache))

    assert first.cached is False
    assert second.cached is True
    assert calls == 1


def test_deep_search_still_fetches_pages(monkeypatch) -> None:
    async def fake_search(**kwargs):
        return SearchResponse(
            query=kwargs["query"],
            provider="duckduckgo_html",
            results=[_search_result("Example", "https://example.com")],
            cached=False,
            error=None,
        )

    async def fake_fetch(url, max_chars):
        return FetchResponse(
            url=url,
            final_url=url,
            title="Example",
            content="Fetched content",
            content_type="text/html",
            cached=False,
            success=True,
            error=None,
        )

    monkeypatch.setattr("mcp_ddg_research.fetch.ddg_search", fake_search)
    monkeypatch.setattr("mcp_ddg_research.fetch.web_fetch", fake_fetch)

    response = asyncio.run(ddg_deep_search(query="example"))

    assert response.search_provider == "duckduckgo_html"
    assert response.pages[0].content == "Fetched content"


def test_no_domain_controls_keeps_provider_request_size_at_max_results(monkeypatch) -> None:
    requested_sizes: list[int] = []
    _install_fake_ddgs(monkeypatch, requested_sizes)

    _search_with_ddgs(SearchRequest(query="example", max_results=4), timeout_seconds=15)

    assert requested_sizes == [4]


def test_preferred_domains_use_expanded_internal_window(monkeypatch) -> None:
    requested_sizes: list[int] = []
    _install_fake_ddgs(monkeypatch, requested_sizes)

    _search_with_ddgs(
        SearchRequest(
            query="example",
            max_results=4,
            preferred_domains=["preferred.example"],
        ),
        timeout_seconds=15,
    )

    assert requested_sizes == [12]


def test_allowed_domains_can_return_match_outside_original_window(monkeypatch, tmp_path) -> None:
    requested_sizes: list[int] = []
    payloads = [
        {"title": "A", "href": "https://first.example/page", "body": ""},
        {"title": "B", "href": "https://second.example/page", "body": ""},
        {"title": "C", "href": "https://allowed.example/page", "body": ""},
    ]
    _install_fake_ddgs(monkeypatch, requested_sizes, payloads=payloads)
    monkeypatch.setenv("SEARCH_PROVIDER", "ddgs")
    monkeypatch.setenv("DDGS_BACKEND", "duckduckgo")

    response = asyncio.run(
        ddg_search(
            query="example",
            max_results=2,
            allowed_domains=["allowed.example"],
            cache=JsonFileCache(tmp_path, "search", ttl_seconds=60),
        )
    )

    assert requested_sizes == [6]
    assert [result.title for result in response.results] == ["C"]


def test_domain_control_results_are_capped_by_max_results(monkeypatch, tmp_path) -> None:
    requested_sizes: list[int] = []
    payloads = [
        {"title": f"Result {index}", "href": f"https://preferred.example/{index}", "body": ""}
        for index in range(6)
    ]
    _install_fake_ddgs(monkeypatch, requested_sizes, payloads=payloads)
    monkeypatch.setenv("SEARCH_PROVIDER", "ddgs")
    monkeypatch.setenv("DDGS_BACKEND", "duckduckgo")

    response = asyncio.run(
        ddg_search(
            query="example",
            max_results=2,
            preferred_domains=["preferred.example"],
            cache=JsonFileCache(tmp_path, "search", ttl_seconds=60),
        )
    )

    assert requested_sizes == [6]
    assert len(response.results) == 2
    assert [result.title for result in response.results] == ["Result 0", "Result 1"]


def test_search_window_overrides_default_internal_window(monkeypatch) -> None:
    requested_sizes: list[int] = []
    _install_fake_ddgs(monkeypatch, requested_sizes)

    _search_with_ddgs(
        SearchRequest(
            query="example",
            max_results=4,
            search_window=9,
            preferred_domains=["preferred.example"],
        ),
        timeout_seconds=15,
    )

    assert requested_sizes == [9]


def test_deep_search_passes_search_window_to_search(monkeypatch) -> None:
    received_search_windows: list[int | None] = []

    async def fake_search(**kwargs):
        received_search_windows.append(kwargs["search_window"])
        return SearchResponse(
            query=kwargs["query"],
            provider="ddgs",
            results=[],
            cached=False,
            error=None,
        )

    monkeypatch.setattr("mcp_ddg_research.fetch.ddg_search", fake_search)

    asyncio.run(ddg_deep_search(query="example", search_window=8))

    assert received_search_windows == [8]


def _install_fake_ddgs(
    monkeypatch,
    requested_sizes: list[int],
    *,
    requested_backends: list[str] | None = None,
    payloads: list[dict[str, str]] | None = None,
) -> None:
    class FakeDDGS:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def text(self, query, **kwargs):
            max_results = kwargs["max_results"]
            requested_sizes.append(max_results)
            if requested_backends is not None:
                requested_backends.append(kwargs.get("backend"))
            if payloads is not None:
                return payloads[:max_results]
            return [
                {
                    "title": f"Result {index}",
                    "href": f"https://example.com/{index}",
                    "body": "",
                }
                for index in range(max_results)
            ]

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FakeDDGS))


def _search_result(title: str, url: str) -> SearchResult:
    return SearchResult(title=title, url=url, snippet="")
