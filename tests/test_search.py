import asyncio
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from mcp_ddg_research.cache import JsonFileCache
from mcp_ddg_research.fetch import ddg_deep_search, get_max_concurrency
from mcp_ddg_research.models import DeepSearchRequest, FetchRequest, SearchRequest, SearchResponse
from mcp_ddg_research.search import (
    _search_with_ddgs,
    ddg_search,
    parse_duckduckgo_html_results,
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
    payloads: list[dict[str, str]] | None = None,
) -> None:
    class FakeDDGS:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def text(self, query, max_results, timelimit, safesearch):
            requested_sizes.append(max_results)
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
