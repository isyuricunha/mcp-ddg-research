"""DuckDuckGo search with ddgs primary provider and HTML fallback."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from mcp_ddg_research.cache import JsonFileCache, build_search_cache, get_env_int
from mcp_ddg_research.domains import apply_domain_controls
from mcp_ddg_research.models import SearchRequest, SearchResponse, SearchResult
from mcp_ddg_research.text import normalize_whitespace

DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
DDGS_SAFE_SEARCH = {"off": "off", "moderate": "moderate", "strict": "on"}
HTML_SAFE_SEARCH = {"off": "-2", "moderate": "-1", "strict": "1"}
TIME_FILTERS = {"day": "d", "week": "w", "month": "m", "year": "y"}
DEFAULT_DDG_TIMEOUT_SECONDS = 15
DEFAULT_DOMAIN_CONTROL_WINDOW_MULTIPLIER = 3
DEFAULT_DOMAIN_CONTROL_WINDOW_CAP = 50
SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_ddg_timeout_seconds() -> int:
    return get_env_int("DDG_TIMEOUT_SECONDS", DEFAULT_DDG_TIMEOUT_SECONDS)


def has_domain_controls(request: SearchRequest) -> bool:
    return bool(
        request.allowed_domains
        or request.blocked_domains
        or request.preferred_domains
    )


def provider_request_size(request: SearchRequest) -> int:
    if request.search_window is not None:
        return request.search_window
    if has_domain_controls(request):
        return min(
            request.max_results * DEFAULT_DOMAIN_CONTROL_WINDOW_MULTIPLIER,
            DEFAULT_DOMAIN_CONTROL_WINDOW_CAP,
        )
    return request.max_results


def resolve_duckduckgo_redirect_url(href: str) -> str:
    if href.startswith("//"):
        resolved = f"https:{href}"
    elif href.startswith("/"):
        resolved = urljoin(DUCKDUCKGO_HTML_URL, href)
    else:
        resolved = href

    parsed = urlparse(resolved)
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    is_duckduckgo_host = hostname == "duckduckgo.com" or hostname.endswith(".duckduckgo.com")
    if is_duckduckgo_host and parsed.path.rstrip("/") == "/l":
        redirect_values = parse_qs(parsed.query).get("uddg")
        if redirect_values and redirect_values[0]:
            return redirect_values[0]
    return resolved


def normalize_url_for_dedupe(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or ""
    if path == "/" and not parsed.query:
        path = ""
    query = urlencode(sorted(parse_qs(parsed.query, keep_blank_values=True).items()), doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def _result_from_payload(payload: dict[str, Any]) -> SearchResult | None:
    title = normalize_whitespace(str(payload.get("title") or ""))
    url = str(payload.get("href") or payload.get("url") or "")
    snippet = normalize_whitespace(str(payload.get("body") or payload.get("snippet") or ""))
    if not title or not url:
        return None
    return SearchResult(title=title, url=resolve_duckduckgo_redirect_url(url), snippet=snippet)


def _dedupe_results(
    results: list[SearchResult],
    max_results: int | None = None,
) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        normalized_url = normalize_url_for_dedupe(result.url)
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        deduped.append(result)
        if max_results is not None and len(deduped) >= max_results:
            break
    return deduped


def _search_with_ddgs(request: SearchRequest, timeout_seconds: int) -> list[SearchResult]:
    from ddgs import DDGS

    timelimit = TIME_FILTERS.get(request.time_filter) if request.time_filter else None
    request_size = provider_request_size(request)
    with DDGS(timeout=timeout_seconds) as ddgs:
        raw_results = ddgs.text(
            request.query,
            max_results=request_size,
            timelimit=timelimit,
            safesearch=DDGS_SAFE_SEARCH[request.safe_search],
        )
    results = [_result_from_payload(result) for result in raw_results or []]
    valid_results = [result for result in results if result is not None]
    return _dedupe_results(valid_results)


def parse_duckduckgo_html_results(html: str, max_results: int) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    for result_node in soup.select(".result"):
        link = result_node.select_one(".result__a")
        if link is None:
            continue
        href = link.get("href")
        title = normalize_whitespace(link.get_text(" ", strip=True))
        if not href or not title:
            continue

        snippet_node = result_node.select_one(".result__snippet")
        snippet = (
            normalize_whitespace(snippet_node.get_text(" ", strip=True)) if snippet_node else ""
        )
        results.append(
            SearchResult(
                title=title,
                url=resolve_duckduckgo_redirect_url(str(href)),
                snippet=snippet,
            )
        )
    return _dedupe_results(results, max_results)


async def _search_with_html_fallback(
    request: SearchRequest,
    timeout_seconds: int,
) -> list[SearchResult]:
    params = {"q": request.query, "kp": HTML_SAFE_SEARCH[request.safe_search]}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=False,
        headers=SEARCH_HEADERS,
    ) as client:
        response = await client.get(DUCKDUCKGO_HTML_URL, params=params)
        response.raise_for_status()
    return parse_duckduckgo_html_results(response.text, provider_request_size(request))


def _cache_payload(request: SearchRequest) -> dict[str, Any]:
    return request.model_dump(mode="json")


def _cacheable_search_response(response: SearchResponse) -> dict[str, Any]:
    return response.model_copy(update={"cached": False}).model_dump(mode="json")


def apply_search_domain_controls(
    results: list[SearchResult],
    request: SearchRequest,
) -> list[SearchResult]:
    filtered_results = apply_domain_controls(
        results,
        get_url=lambda result: result.url,
        allowed_domains=request.allowed_domains,
        blocked_domains=request.blocked_domains,
        preferred_domains=request.preferred_domains,
    )
    return filtered_results[: request.max_results]


async def ddg_search(
    query: str,
    max_results: int = 10,
    search_window: int | None = None,
    safe_search: str = "off",
    time_filter: str | None = None,
    blocked_domains: list[str] | None = None,
    allowed_domains: list[str] | None = None,
    preferred_domains: list[str] | None = None,
    *,
    cache: JsonFileCache | None = None,
) -> SearchResponse:
    request = SearchRequest(
        query=query,
        max_results=max_results,
        search_window=search_window,
        safe_search=safe_search,
        time_filter=time_filter,
        blocked_domains=blocked_domains or [],
        allowed_domains=allowed_domains or [],
        preferred_domains=preferred_domains or [],
    )
    cache = cache or build_search_cache()
    payload = _cache_payload(request)
    cached_value = cache.get(payload)
    if cached_value is not None:
        return SearchResponse.model_validate(cached_value).model_copy(update={"cached": True})

    timeout_seconds = get_ddg_timeout_seconds()
    provider_errors: list[str] = []

    try:
        ddgs_results = apply_search_domain_controls(
            await asyncio.to_thread(_search_with_ddgs, request, timeout_seconds),
            request,
        )
        if ddgs_results:
            response = SearchResponse(
                query=request.query,
                provider="ddgs",
                results=ddgs_results,
                cached=False,
                error=None,
            )
            cache.set(payload, _cacheable_search_response(response))
            return response
        provider_errors.append("ddgs returned no results")
    except Exception as exc:  # noqa: BLE001 - provider failures must not crash the server.
        provider_errors.append(f"ddgs failed: {exc}")

    try:
        html_results = apply_search_domain_controls(
            await _search_with_html_fallback(request, timeout_seconds),
            request,
        )
        if html_results:
            response = SearchResponse(
                query=request.query,
                provider="duckduckgo_html",
                results=html_results,
                cached=False,
                error=None,
            )
            cache.set(payload, _cacheable_search_response(response))
            return response
        provider_errors.append("duckduckgo_html returned no results")
    except Exception as exc:  # noqa: BLE001 - provider failures must not crash the server.
        provider_errors.append(f"duckduckgo_html failed: {exc}")

    return SearchResponse(
        query=request.query,
        provider="duckduckgo_html",
        results=[],
        cached=False,
        error="; ".join(provider_errors) or "Search failed",
    )
