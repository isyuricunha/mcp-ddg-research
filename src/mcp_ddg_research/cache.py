"""Small file-based JSON cache with atomic writes."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import suppress
from hashlib import sha256
from pathlib import Path
from typing import Any

DEFAULT_CACHE_DIR = "/data/cache"
DEFAULT_SEARCH_TTL_SECONDS = 21_600
DEFAULT_FETCH_TTL_SECONDS = 7_200


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def get_cache_dir() -> Path:
    return Path(os.getenv("MCP_CACHE_DIR", DEFAULT_CACHE_DIR))


def stable_cache_key(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


class JsonFileCache:
    """TTL-based JSON cache backed by one file per key."""

    def __init__(self, root_dir: Path, namespace: str, ttl_seconds: int) -> None:
        self.root_dir = root_dir
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds
        self.cache_dir = self.root_dir / namespace
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, payload: Any) -> Path:
        return self.cache_dir / f"{stable_cache_key(payload)}.json"

    def get(self, payload: Any) -> dict[str, Any] | None:
        path = self.path_for(payload)
        try:
            with path.open("r", encoding="utf-8") as cache_file:
                envelope = json.load(cache_file)
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            return None

        created_at = envelope.get("created_at")
        value = envelope.get("value")
        if not isinstance(created_at, int | float) or not isinstance(value, dict):
            return None
        if time.time() - float(created_at) > self.ttl_seconds:
            return None
        return value

    def set(self, payload: Any, value: dict[str, Any]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(payload)
        envelope = {"created_at": time.time(), "value": value}

        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.cache_dir,
                delete=False,
                prefix=f".{path.stem}.",
                suffix=".tmp",
            ) as temp_file:
                temp_path = temp_file.name
                json.dump(envelope, temp_file, ensure_ascii=False, sort_keys=True)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                with suppress(OSError):
                    Path(temp_path).unlink(missing_ok=True)


def build_search_cache() -> JsonFileCache:
    ttl = get_env_int("DDG_CACHE_TTL_SECONDS", DEFAULT_SEARCH_TTL_SECONDS)
    return JsonFileCache(get_cache_dir(), "search", ttl)


def build_fetch_cache() -> JsonFileCache:
    ttl = get_env_int("FETCH_CACHE_TTL_SECONDS", DEFAULT_FETCH_TTL_SECONDS)
    return JsonFileCache(get_cache_dir(), "fetch", ttl)
