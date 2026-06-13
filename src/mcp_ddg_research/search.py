"""DuckDuckGo-focused search with optional ddgs provider support."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import os
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
DEFAULT_SEARCH_PROVIDER = "duckduckgo_html"
DEFAULT_DDGS_BACKEND = "duckduckgo"
SEARCH_PROVIDERS = {"duckduckgo_html", "ddgs", "auto"}
DEFAULT_DDG_TIMEOUT_SECONDS = 15
DEFAULT_DOMAIN_CONTROL_WINDOW_MULTIPLIER = 3
DEFAULT_DOMAIN_CONTROL_WINDOW_CAP = 50
LOGGER = logging.getLogger(__name__)
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


def get_search_provider() -> str:
    provider = os.getenv("SEARCH_PROVIDER", DEFAULT_SEARCH_PROVIDER).strip().lower()
    if provider in SEARCH_PROVIDERS:
        return provider
    LOGGER.warning(
        "Invalid SEARCH_PROVIDER=%r; falling back to %s",
        provider,
        DEFAULT_SEARCH_PROVIDER,
    )
    return DEFAULT_SEARCH_PROVIDER


def is_valid_search_provider(provider: str) -> bool:
    return provider.strip().lower() in SEARCH_PROVIDERS


def _available_ddgs_text_backends() -> set[str] | None:
    try:
        ddgs_module = importlib.import_module("ddgs.ddgs")
    except Exception:  # noqa: BLE001 - ddgs is optional at runtime unless selected.
        return None

    engines = getattr(ddgs_module, "ENGINES", None)
    if not isinstance(engines, dict):
        return None
    text_engines = engines.get("text")
    if not isinstance(text_engines, dict):
        return None
    return {str(backend).lower() for backend in text_engines}


def get_ddgs_backend() -> str:
    backend = os.getenv("DDGS_BACKEND", DEFAULT_DDGS_BACKEND).strip().lower()
    if not backend:
        return DEFAULT_DDGS_BACKEND
    if backend == "auto":
        return backend

    requested_backends = [part.strip() for part in backend.split(",") if part.strip()]
    if not requested_backends:
        return DEFAULT_DDGS_BACKEND

    available_backends = _available_ddgs_text_backends()
    if available_backends is None:
        return ",".join(requested_backends)

    invalid_backends = [
        requested_backend
        for requested_backend in requested_backends
        if requested_backend not in available_backends
    ]
    if invalid_backends:
        LOGGER.warning(
            "Invalid DDGS_BACKEND=%r; falling back to %s",
            backend,
            DEFAULT_DDGS_BACKEND,
        )
        return DEFAULT_DDGS_BACKEND
    return ",".join(requested_backends)


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


def _signature_accepts_parameter(signature: inspect.Signature, parameter_name: str) -> bool:
    return parameter_name in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _ddgs_text_kwargs(
    request: SearchRequest,
    backend: str,
    *,
    include_backend: bool,
) -> dict[str, Any]:
    timelimit = TIME_FILTERS.get(request.time_filter) if request.time_filter else None
    kwargs: dict[str, Any] = {
        "max_results": provider_request_size(request),
        "timelimit": timelimit,
        "safesearch": DDGS_SAFE_SEARCH[request.safe_search],
    }
    if include_backend:
        kwargs["backend"] = backend
    return kwargs


def _search_with_ddgs(
    request: SearchRequest,
    timeout_seconds: int,
    backend: str = DEFAULT_DDGS_BACKEND,
) -> list[SearchResult]:
    from ddgs import DDGS

    with DDGS(timeout=timeout_seconds) as ddgs:
        text_signature = inspect.signature(ddgs.text)
        include_backend = _signature_accepts_parameter(text_signature, "backend")
        kwargs = _ddgs_text_kwargs(request, backend, include_backend=include_backend)
        LOGGER.debug(
            "Running ddgs search with backend=%s",
            backend if include_backend else "unsupported",
        )
        try:
            raw_results = ddgs.text(request.query, **kwargs)
        except TypeError as exc:
            if include_backend and "backend" in str(exc):
                kwargs.pop("backend", None)
                LOGGER.debug("Retrying ddgs search without backend parameter")
                raw_results = ddgs.text(request.query, **kwargs)
            else:
                raise
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


async def _search_with_duckduckgo_html(
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


def _cache_payload(
    request: SearchRequest,
    *,
    provider: str,
    ddgs_backend: str | None,
) -> dict[str, Any]:
    payload = request.model_dump(mode="json")
    payload["_provider"] = provider
    if ddgs_backend is not None:
        payload["_ddgs_backend"] = ddgs_backend
    return payload


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
    provider = get_search_provider()
    ddgs_backend = get_ddgs_backend() if provider in {"ddgs", "auto"} else None
    payload = _cache_payload(request, provider=provider, ddgs_backend=ddgs_backend)
    cached_value = cache.get(payload)
    if cached_value is not None:
        return SearchResponse.model_validate(cached_value).model_copy(update={"cached": True})

    timeout_seconds = get_ddg_timeout_seconds()
    provider_errors: list[str] = []

    if provider in {"duckduckgo_html", "auto"}:
        try:
            LOGGER.debug("Running DuckDuckGo HTML search")
            html_results = apply_search_domain_controls(
                await _search_with_duckduckgo_html(request, timeout_seconds),
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

    if provider in {"ddgs", "auto"}:
        backend = ddgs_backend or DEFAULT_DDGS_BACKEND
        try:
            ddgs_results = apply_search_domain_controls(
                await asyncio.to_thread(_search_with_ddgs, request, timeout_seconds, backend),
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
            provider_errors.append(f"ddgs backend {backend} returned no results")
        except Exception as exc:  # noqa: BLE001 - provider failures must not crash the server.
            provider_errors.append(f"ddgs backend {backend} failed: {exc}")

    return SearchResponse(
        query=request.query,
        provider="duckduckgo_html",
        results=[],
        cached=False,
        error="; ".join(provider_errors) or "Search failed",
    )
