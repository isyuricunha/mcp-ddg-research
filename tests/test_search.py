import pytest
from pydantic import ValidationError

from mcp_ddg_research.fetch import get_max_concurrency
from mcp_ddg_research.models import DeepSearchRequest, SearchRequest
from mcp_ddg_research.search import (
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


def test_search_request_rejects_invalid_safe_search() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="example", safe_search="disabled")


def test_deep_search_request_accepts_max_concurrency() -> None:
    request = DeepSearchRequest(query="example", max_concurrency=12)

    assert request.max_concurrency == 12


def test_deep_search_request_rejects_invalid_max_concurrency() -> None:
    with pytest.raises(ValidationError):
        DeepSearchRequest(query="example", max_concurrency=13)


def test_get_max_concurrency_uses_per_call_value() -> None:
    assert get_max_concurrency(max_concurrency=3) == 3
