import asyncio
import json
import os
import time

import pytest

from mcp_ddg_research.cache import (
    CACHE_NAMESPACES,
    CachePruneConfig,
    JsonFileCache,
    clear_cache,
    get_cache_stats,
    maybe_prune_cache,
    prune_cache,
)
from mcp_ddg_research.fetch import web_fetch
from mcp_ddg_research.models import FetchRequest, FetchResponse, SearchRequest, SearchResponse
from mcp_ddg_research.search import ddg_search


def _write_cache_file(path, *, created_at: float, value: dict | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": created_at, "value": value or {"ok": True}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.stat().st_size


def _prune_config(
    root_dir,
    *,
    search_ttl: int = 60,
    fetch_ttl: int = 60,
    max_age_seconds: int | None = None,
    max_size_bytes: int | None = None,
    prune_interval_seconds: int = 3600,
) -> CachePruneConfig:
    return CachePruneConfig(
        root_dir=root_dir,
        prune_on_start=True,
        prune_interval_seconds=prune_interval_seconds,
        max_age_seconds=max_age_seconds,
        max_size_bytes=max_size_bytes,
        namespace_ttls={"search": search_ttl, "fetch": fetch_ttl},
    )


def test_cache_read_write_works(tmp_path) -> None:
    cache = JsonFileCache(tmp_path, "search", ttl_seconds=60)
    payload = {"query": "example", "max_results": 10}
    value = {"results": [{"title": "Example", "url": "https://example.com"}]}

    cache.set(payload, value)

    assert cache.get(payload) == value


def test_cache_ignores_corrupt_files(tmp_path) -> None:
    cache = JsonFileCache(tmp_path, "fetch", ttl_seconds=60)
    path = cache.path_for({"url": "https://example.com"})
    path.write_text("{not-json", encoding="utf-8")

    assert cache.get({"url": "https://example.com"}) is None


def test_cache_ignores_expired_files(tmp_path) -> None:
    cache = JsonFileCache(tmp_path, "search", ttl_seconds=1)
    payload = {"query": "expired"}
    path = cache.path_for(payload)
    path.write_text(
        json.dumps({"created_at": time.time() - 10, "value": {"result": "old"}}),
        encoding="utf-8",
    )

    assert cache.get(payload) is None


def test_prune_deletes_expired_files(tmp_path) -> None:
    path = tmp_path / "search" / "expired.json"
    _write_cache_file(path, created_at=time.time() - 120)

    stats = prune_cache(config=_prune_config(tmp_path, search_ttl=60))

    assert stats.deleted_files == 1
    assert path.exists() is False


def test_cache_stats_reports_namespace_and_total_sizes(tmp_path) -> None:
    search_size = _write_cache_file(tmp_path / "search" / "entry.json", created_at=time.time())
    fetch_size = _write_cache_file(tmp_path / "fetch" / "entry.json", created_at=time.time())

    stats = get_cache_stats(tmp_path)
    payload = stats.to_dict()

    assert payload["cache_dir"] == str(tmp_path)
    assert payload["namespaces"]["search"] == {"files": 1, "bytes": search_size}
    assert payload["namespaces"]["fetch"] == {"files": 1, "bytes": fetch_size}
    assert payload["total_files"] == 2
    assert payload["total_bytes"] == search_size + fetch_size


def test_prune_deletes_corrupt_json_files(tmp_path) -> None:
    path = tmp_path / "fetch" / "corrupt.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    stats = prune_cache(config=_prune_config(tmp_path))

    assert stats.deleted_files == 1
    assert path.exists() is False


def test_prune_deletes_leftover_tmp_files(tmp_path) -> None:
    path = tmp_path / "search" / ".leftover.tmp"
    path.parent.mkdir(parents=True)
    path.write_text("temporary", encoding="utf-8")
    old_timestamp = time.time() - 120
    os.utime(path, (old_timestamp, old_timestamp))

    stats = prune_cache(config=_prune_config(tmp_path))

    assert stats.deleted_files == 1
    assert path.exists() is False


def test_prune_max_age_deletes_old_files(tmp_path) -> None:
    old_path = tmp_path / "search" / "old.json"
    new_path = tmp_path / "search" / "new.json"
    _write_cache_file(old_path, created_at=time.time() - 120)
    _write_cache_file(new_path, created_at=time.time())

    stats = prune_cache(config=_prune_config(tmp_path, max_age_seconds=60))

    assert stats.deleted_files == 1
    assert old_path.exists() is False
    assert new_path.exists() is True


def test_prune_max_size_deletes_oldest_files_first(tmp_path) -> None:
    now = time.time()
    oldest_path = tmp_path / "search" / "oldest.json"
    middle_path = tmp_path / "fetch" / "middle.json"
    newest_path = tmp_path / "fetch" / "newest.json"
    oldest_size = _write_cache_file(oldest_path, created_at=now - 30, value={"payload": "a" * 40})
    middle_size = _write_cache_file(middle_path, created_at=now - 20, value={"payload": "b" * 40})
    newest_size = _write_cache_file(newest_path, created_at=now - 10, value={"payload": "c" * 40})
    max_size = middle_size + newest_size

    stats = prune_cache(config=_prune_config(tmp_path, max_size_bytes=max_size))

    assert stats.deleted_files == 1
    assert stats.deleted_bytes == oldest_size
    assert oldest_path.exists() is False
    assert middle_path.exists() is True
    assert newest_path.exists() is True


def test_prune_dry_run_reports_deletions_without_deleting(tmp_path) -> None:
    path = tmp_path / "search" / "expired.json"
    size = _write_cache_file(path, created_at=time.time() - 120)

    stats = prune_cache(config=_prune_config(tmp_path, search_ttl=60), dry_run=True)

    assert stats.deleted_files == 1
    assert stats.deleted_bytes == size
    assert stats.dry_run is True
    assert path.exists() is True


def test_cache_clear_requires_confirm_true(tmp_path) -> None:
    path = tmp_path / "search" / "entry.json"
    _write_cache_file(path, created_at=time.time())

    stats = clear_cache(namespace="search", confirm=False, root_dir=tmp_path)

    assert stats.deleted_files == 0
    assert stats.error == "confirm must be true to clear cache files"
    assert path.exists() is True


@pytest.mark.parametrize(
    ("namespace", "remaining_namespaces"),
    [
        ("search", {"fetch"}),
        ("fetch", {"search"}),
        ("all", set()),
    ],
)
def test_cache_clear_can_clear_namespaces(tmp_path, namespace, remaining_namespaces) -> None:
    for cache_namespace in CACHE_NAMESPACES:
        _write_cache_file(
            tmp_path / cache_namespace / "entry.json",
            created_at=time.time(),
        )

    stats = clear_cache(namespace=namespace, confirm=True, root_dir=tmp_path)

    assert stats.deleted_files == (2 if namespace == "all" else 1)
    for cache_namespace in CACHE_NAMESPACES:
        path = tmp_path / cache_namespace / "entry.json"
        assert path.exists() is (cache_namespace in remaining_namespaces)


def test_maybe_prune_cache_does_not_run_more_often_than_interval(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_prune_cache(*, config, expired_only=False, dry_run=False):
        calls.append((config.root_dir, expired_only, dry_run))
        return None

    monkeypatch.setattr("mcp_ddg_research.cache.prune_cache", fake_prune_cache)
    monkeypatch.setattr("mcp_ddg_research.cache._LAST_PRUNE_TIMES", {})
    monkeypatch.setenv("CACHE_PRUNE_INTERVAL_SECONDS", "3600")

    maybe_prune_cache(root_dir=tmp_path)
    maybe_prune_cache(root_dir=tmp_path)

    assert len(calls) == 1


def test_search_still_uses_cache_if_pruning_fails(monkeypatch, tmp_path) -> None:
    cache = JsonFileCache(tmp_path, "search", ttl_seconds=60)
    request = SearchRequest(query="example")
    response = SearchResponse(
        query="example",
        provider="ddgs",
        results=[],
        cached=False,
        error=None,
    )
    cache.set(request.model_dump(mode="json"), response.model_dump(mode="json"))

    def fail_prune(*args, **kwargs):
        raise OSError("prune failed")

    monkeypatch.setattr("mcp_ddg_research.cache.prune_cache", fail_prune)
    monkeypatch.setattr("mcp_ddg_research.cache._LAST_PRUNE_TIMES", {})

    cached_response = asyncio.run(ddg_search(query="example", cache=cache))

    assert cached_response.cached is True
    assert cached_response.error is None


def test_fetch_still_uses_cache_if_pruning_fails(monkeypatch, tmp_path) -> None:
    cache = JsonFileCache(tmp_path, "fetch", ttl_seconds=60)
    request = FetchRequest(url="https://example.com", max_chars=12000)
    response = FetchResponse(
        url="https://example.com",
        final_url="https://example.com",
        title="Example",
        content="Cached content",
        content_type="text/html",
        cached=False,
        success=True,
        error=None,
    )
    cache.set(request.model_dump(mode="json"), response.model_dump(mode="json"))

    async def validate_without_dns(url: str) -> None:
        return None

    def fail_prune(*args, **kwargs):
        raise OSError("prune failed")

    monkeypatch.setattr("mcp_ddg_research.fetch.validate_fetch_url", validate_without_dns)
    monkeypatch.setattr("mcp_ddg_research.cache.prune_cache", fail_prune)
    monkeypatch.setattr("mcp_ddg_research.cache._LAST_PRUNE_TIMES", {})

    cached_response = asyncio.run(web_fetch(url="https://example.com", cache=cache))

    assert cached_response.cached is True
    assert cached_response.content == "Cached content"
