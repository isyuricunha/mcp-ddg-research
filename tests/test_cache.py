import json
import time

from mcp_ddg_research.cache import JsonFileCache


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
