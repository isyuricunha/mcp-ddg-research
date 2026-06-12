"""Domain normalization and opt-in search result controls."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from urllib.parse import urlparse


def normalize_domain(value: str) -> str:
    raw_value = value.strip().lower()
    if not raw_value:
        return ""

    parsed = urlparse(raw_value if "://" in raw_value else f"//{raw_value}")
    hostname = parsed.hostname or raw_value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    normalized = hostname.rstrip(".")
    if normalized.startswith("www."):
        normalized = normalized[4:]
    return normalized


def normalize_domains(values: Iterable[str]) -> list[str]:
    normalized_domains: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_domain(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_domains.append(normalized)
    return normalized_domains


def domain_matches(hostname: str, domain: str) -> bool:
    normalized_hostname = normalize_domain(hostname)
    normalized_domain = normalize_domain(domain)
    if not normalized_hostname or not normalized_domain:
        return False
    return normalized_hostname == normalized_domain or normalized_hostname.endswith(
        f".{normalized_domain}"
    )


def url_matches_domains(url: str, domains: Sequence[str]) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    return any(domain_matches(parsed.hostname, domain) for domain in domains)


def apply_domain_controls[T](
    items: Sequence[T],
    *,
    get_url: Callable[[T], str],
    allowed_domains: Sequence[str],
    blocked_domains: Sequence[str],
    preferred_domains: Sequence[str],
) -> list[T]:
    controlled_items = list(items)

    if allowed_domains:
        controlled_items = [
            item for item in controlled_items if url_matches_domains(get_url(item), allowed_domains)
        ]

    if blocked_domains:
        controlled_items = [
            item
            for item in controlled_items
            if not url_matches_domains(get_url(item), blocked_domains)
        ]

    if preferred_domains:
        preferred_items = [
            item
            for item in controlled_items
            if url_matches_domains(get_url(item), preferred_domains)
        ]
        other_items = [
            item
            for item in controlled_items
            if not url_matches_domains(get_url(item), preferred_domains)
        ]
        controlled_items = [*preferred_items, *other_items]

    return controlled_items
