"""URL safety checks for SSRF-resistant fetching."""

from __future__ import annotations

import asyncio
import socket
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from urllib.parse import urlparse

BLOCKED_HOSTNAMES = {"localhost", "metadata", "metadata.google.internal"}
BLOCKED_HOSTNAME_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".intranet")
BLOCKED_NETWORKS: tuple[IPv4Network | IPv6Network, ...] = (
    ip_network("0.0.0.0/8"),
    ip_network("10.0.0.0/8"),
    ip_network("127.0.0.0/8"),
    ip_network("169.254.0.0/16"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("::1/128"),
    ip_network("fc00::/7"),
    ip_network("fe80::/10"),
)


class UnsafeUrlError(ValueError):
    """Raised when a URL is not safe to fetch."""


def _normalize_hostname(hostname: str) -> str:
    return hostname.rstrip(".").lower()


def is_blocked_hostname(hostname: str) -> bool:
    normalized = _normalize_hostname(hostname)
    return normalized in BLOCKED_HOSTNAMES or normalized.endswith(BLOCKED_HOSTNAME_SUFFIXES)


def is_unsafe_ip(value: str) -> bool:
    try:
        ip = ip_address(value)
    except ValueError:
        return False

    if any(ip in network for network in BLOCKED_NETWORKS):
        return True
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_reserved,
            ip.is_multicast,
            ip.is_unspecified,
        )
    )


def validate_url_shape(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("Only http and https URLs are allowed")
    if not parsed.hostname:
        raise UnsafeUrlError("URL must include a hostname")

    hostname = _normalize_hostname(parsed.hostname)
    if is_blocked_hostname(hostname):
        raise UnsafeUrlError(f"Blocked internal hostname: {hostname}")
    if is_unsafe_ip(hostname):
        raise UnsafeUrlError(f"Blocked unsafe IP address: {hostname}")


def _resolve_hostname(hostname: str, port: int) -> set[str]:
    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"DNS resolution failed for {hostname}") from exc

    addresses: set[str] = set()
    for record in records:
        sockaddr = record[4]
        if sockaddr:
            addresses.add(str(sockaddr[0]))
    if not addresses:
        raise UnsafeUrlError(f"DNS resolution returned no addresses for {hostname}")
    return addresses


def validate_resolved_addresses(url: str) -> None:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        raise UnsafeUrlError("URL must include a hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    for resolved_ip in _resolve_hostname(hostname, port):
        if is_unsafe_ip(resolved_ip):
            raise UnsafeUrlError(f"DNS resolved to unsafe IP address: {resolved_ip}")


async def validate_fetch_url(url: str) -> None:
    validate_url_shape(url)
    await asyncio.to_thread(validate_resolved_addresses, url)
