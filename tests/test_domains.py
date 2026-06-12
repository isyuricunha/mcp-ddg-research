from mcp_ddg_research.domains import (
    apply_domain_controls,
    domain_matches,
    normalize_domain,
)
from mcp_ddg_research.models import SearchResult
from mcp_ddg_research.search import apply_search_domain_controls


def _result(title: str, url: str) -> SearchResult:
    return SearchResult(title=title, url=url, snippet="")


def test_domain_matching_supports_exact_domain() -> None:
    assert domain_matches("example.com", "example.com") is True


def test_domain_matching_supports_subdomains() -> None:
    assert domain_matches("docs.example.com", "example.com") is True


def test_domain_matching_rejects_lookalike_domains() -> None:
    assert domain_matches("example.com.evil.com", "example.com") is False


def test_normalize_domain_strips_scheme_path_query_and_www() -> None:
    assert normalize_domain("https://www.Example.com/docs?x=1") == "example.com"


def test_blocked_domains_filtering() -> None:
    results = [
        _result("A", "https://alpha.example/page"),
        _result("B", "https://blocked.example/page"),
        _result("C", "https://docs.blocked.example/page"),
    ]

    filtered = apply_domain_controls(
        results,
        get_url=lambda result: result.url,
        allowed_domains=[],
        blocked_domains=["blocked.example"],
        preferred_domains=[],
    )

    assert [result.title for result in filtered] == ["A"]


def test_allowed_domains_filtering() -> None:
    results = [
        _result("A", "https://alpha.example/page"),
        _result("B", "https://docs.allowed.example/page"),
        _result("C", "https://other.example/page"),
    ]

    filtered = apply_domain_controls(
        results,
        get_url=lambda result: result.url,
        allowed_domains=["allowed.example"],
        blocked_domains=[],
        preferred_domains=[],
    )

    assert [result.title for result in filtered] == ["B"]


def test_preferred_domains_stable_ordering() -> None:
    results = [
        _result("A", "https://first.example/page"),
        _result("B", "https://preferred.example/page-1"),
        _result("C", "https://other.example/page"),
        _result("D", "https://docs.preferred.example/page-2"),
    ]

    filtered = apply_domain_controls(
        results,
        get_url=lambda result: result.url,
        allowed_domains=[],
        blocked_domains=[],
        preferred_domains=["preferred.example"],
    )

    assert [result.title for result in filtered] == ["B", "D", "A", "C"]


def test_empty_domain_controls_preserve_original_order() -> None:
    results = [
        _result("A", "https://first.example/page"),
        _result("B", "https://second.example/page"),
        _result("C", "https://third.example/page"),
    ]

    filtered = apply_domain_controls(
        results,
        get_url=lambda result: result.url,
        allowed_domains=[],
        blocked_domains=[],
        preferred_domains=[],
    )

    assert filtered == results


def test_search_domain_controls_apply_allowed_then_blocked_then_preferred() -> None:
    from mcp_ddg_research.models import SearchRequest

    request = SearchRequest(
        query="example",
        allowed_domains=["example.com"],
        blocked_domains=["blocked.example.com"],
        preferred_domains=["preferred.example.com"],
    )
    results = [
        _result("A", "https://neutral.example.com/page"),
        _result("B", "https://blocked.example.com/page"),
        _result("C", "https://preferred.example.com/page"),
        _result("D", "https://outside.test/page"),
    ]

    filtered = apply_search_domain_controls(results, request)

    assert [result.title for result in filtered] == ["C", "A"]
