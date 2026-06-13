"""Small file-based JSON cache with atomic writes."""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

DEFAULT_CACHE_DIR = "/data/cache"
DEFAULT_SEARCH_TTL_SECONDS = 21_600
DEFAULT_FETCH_TTL_SECONDS = 7_200
DEFAULT_CACHE_PRUNE_INTERVAL_SECONDS = 3_600
TEMP_FILE_PRUNE_GRACE_SECONDS = 60
CACHE_NAMESPACES = ("search", "fetch")

LOGGER = logging.getLogger(__name__)
_PRUNE_LOCK = threading.Lock()
_LAST_PRUNE_TIMES: dict[str, float] = {}


@dataclass(frozen=True)
class CachePruneConfig:
    root_dir: Path
    prune_on_start: bool
    prune_interval_seconds: int
    max_age_seconds: int | None
    max_size_bytes: int | None
    namespace_ttls: dict[str, int]


@dataclass(frozen=True)
class CacheNamespaceStats:
    files: int
    bytes: int

    def to_dict(self) -> dict[str, int]:
        return {"files": self.files, "bytes": self.bytes}


@dataclass(frozen=True)
class CacheStats:
    cache_dir: str
    namespaces: dict[str, CacheNamespaceStats]
    total_files: int
    total_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_dir": self.cache_dir,
            "namespaces": {
                namespace: stats.to_dict()
                for namespace, stats in self.namespaces.items()
            },
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
        }


@dataclass(frozen=True)
class CachePruneStats:
    deleted_files: int
    deleted_bytes: int
    remaining_files: int
    remaining_bytes: int
    dry_run: bool

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "deleted_files": self.deleted_files,
            "deleted_bytes": self.deleted_bytes,
            "remaining_files": self.remaining_files,
            "remaining_bytes": self.remaining_bytes,
            "dry_run": self.dry_run,
        }


@dataclass(frozen=True)
class CacheClearStats:
    namespace: str
    deleted_files: int
    deleted_bytes: int
    error: str | None = None

    def to_dict(self) -> dict[str, int | str | None]:
        response: dict[str, int | str | None] = {
            "namespace": self.namespace,
            "deleted_files": self.deleted_files,
            "deleted_bytes": self.deleted_bytes,
        }
        if self.error is not None:
            response["error"] = self.error
        return response


@dataclass(frozen=True)
class _CacheFile:
    namespace: str
    path: Path
    size: int
    mtime: float


@dataclass(frozen=True)
class _ValidCacheFile:
    path: Path
    size: int
    created_at: float


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _get_optional_positive_env_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _get_env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def get_cache_dir() -> Path:
    return Path(os.getenv("MCP_CACHE_DIR", DEFAULT_CACHE_DIR))


def get_cache_prune_config(root_dir: Path | None = None) -> CachePruneConfig:
    max_size_mb = _get_optional_positive_env_int("CACHE_MAX_SIZE_MB")
    return CachePruneConfig(
        root_dir=root_dir or get_cache_dir(),
        prune_on_start=_get_env_bool("CACHE_PRUNE_ON_START", True),
        prune_interval_seconds=get_env_int(
            "CACHE_PRUNE_INTERVAL_SECONDS",
            DEFAULT_CACHE_PRUNE_INTERVAL_SECONDS,
        ),
        max_age_seconds=_get_optional_positive_env_int("CACHE_MAX_AGE_SECONDS"),
        max_size_bytes=max_size_mb * 1024 * 1024 if max_size_mb is not None else None,
        namespace_ttls={
            "search": get_env_int("DDG_CACHE_TTL_SECONDS", DEFAULT_SEARCH_TTL_SECONDS),
            "fetch": get_env_int("FETCH_CACHE_TTL_SECONDS", DEFAULT_FETCH_TTL_SECONDS),
        },
    )


def stable_cache_key(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _ensure_cache_namespace_dirs(root_dir: Path) -> None:
    with suppress(OSError):
        root_dir.mkdir(parents=True, exist_ok=True)
    if not root_dir.is_dir():
        return

    for namespace in CACHE_NAMESPACES:
        namespace_dir = root_dir / namespace
        if namespace_dir.is_symlink() or (namespace_dir.exists() and not namespace_dir.is_dir()):
            continue
        with suppress(OSError):
            namespace_dir.mkdir(parents=True, exist_ok=True)


def _iter_cache_files(root_dir: Path) -> list[_CacheFile]:
    files: list[_CacheFile] = []
    for namespace in CACHE_NAMESPACES:
        namespace_dir = root_dir / namespace
        if namespace_dir.is_symlink() or not namespace_dir.is_dir():
            continue

        with suppress(OSError):
            entries = list(namespace_dir.iterdir())
            for path in entries:
                if path.suffix not in {".json", ".tmp"}:
                    continue
                try:
                    file_stat = path.stat(follow_symlinks=False)
                except OSError:
                    continue
                if not stat.S_ISREG(file_stat.st_mode):
                    continue
                files.append(
                    _CacheFile(
                        namespace=namespace,
                        path=path,
                        size=file_stat.st_size,
                        mtime=file_stat.st_mtime,
                    )
                )
    return files


def _read_cache_created_at(path: Path) -> float | None:
    try:
        with path.open("r", encoding="utf-8") as cache_file:
            envelope = json.load(cache_file)
    except (json.JSONDecodeError, OSError, TypeError):
        return None

    if not isinstance(envelope, dict):
        return None
    created_at = envelope.get("created_at")
    value = envelope.get("value")
    if not isinstance(created_at, int | float) or not isinstance(value, dict):
        return None
    return float(created_at)


def _delete_cache_file(path: Path) -> bool:
    try:
        file_stat = path.stat(follow_symlinks=False)
    except OSError:
        return False
    if not stat.S_ISREG(file_stat.st_mode):
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def get_cache_stats(root_dir: Path | None = None) -> CacheStats:
    root = root_dir or get_cache_dir()
    _ensure_cache_namespace_dirs(root)

    namespace_totals = {
        namespace: CacheNamespaceStats(files=0, bytes=0)
        for namespace in CACHE_NAMESPACES
    }
    for cache_file in _iter_cache_files(root):
        current = namespace_totals[cache_file.namespace]
        namespace_totals[cache_file.namespace] = CacheNamespaceStats(
            files=current.files + 1,
            bytes=current.bytes + cache_file.size,
        )

    total_files = sum(stats.files for stats in namespace_totals.values())
    total_bytes = sum(stats.bytes for stats in namespace_totals.values())
    return CacheStats(
        cache_dir=str(root),
        namespaces=namespace_totals,
        total_files=total_files,
        total_bytes=total_bytes,
    )


def prune_cache(
    *,
    config: CachePruneConfig | None = None,
    expired_only: bool = False,
    dry_run: bool = False,
) -> CachePruneStats:
    prune_config = config or get_cache_prune_config()
    root = prune_config.root_dir
    _ensure_cache_namespace_dirs(root)
    now = time.time()

    delete_candidates: dict[Path, int] = {}
    retained_json_files: list[_ValidCacheFile] = []

    for cache_file in _iter_cache_files(root):
        if cache_file.path.suffix == ".tmp":
            if now - cache_file.mtime > TEMP_FILE_PRUNE_GRACE_SECONDS:
                delete_candidates[cache_file.path] = cache_file.size
            continue

        created_at = _read_cache_created_at(cache_file.path)
        if created_at is None:
            delete_candidates[cache_file.path] = cache_file.size
            continue

        namespace_ttl = prune_config.namespace_ttls[cache_file.namespace]
        if now - created_at > namespace_ttl:
            delete_candidates[cache_file.path] = cache_file.size
            continue

        if (
            prune_config.max_age_seconds is not None
            and now - created_at > prune_config.max_age_seconds
        ):
            delete_candidates[cache_file.path] = cache_file.size
            continue

        retained_json_files.append(
            _ValidCacheFile(
                path=cache_file.path,
                size=cache_file.size,
                created_at=created_at,
            )
        )

    if not expired_only and prune_config.max_size_bytes is not None:
        retained_size = sum(cache_file.size for cache_file in retained_json_files)
        for cache_file in sorted(
            retained_json_files,
            key=lambda item: (item.created_at, item.path.name),
        ):
            if retained_size <= prune_config.max_size_bytes:
                break
            delete_candidates[cache_file.path] = cache_file.size
            retained_size -= cache_file.size

    deleted_files = 0
    deleted_bytes = 0
    for path, size in delete_candidates.items():
        if dry_run:
            deleted_files += 1
            deleted_bytes += size
            continue
        if _delete_cache_file(path):
            deleted_files += 1
            deleted_bytes += size

    remaining = get_cache_stats(root)
    return CachePruneStats(
        deleted_files=deleted_files,
        deleted_bytes=deleted_bytes,
        remaining_files=remaining.total_files,
        remaining_bytes=remaining.total_bytes,
        dry_run=dry_run,
    )


def maybe_prune_cache(
    *,
    root_dir: Path | None = None,
    force: bool = False,
) -> CachePruneStats | None:
    config = get_cache_prune_config(root_dir)
    now = time.monotonic()
    cache_key = str(config.root_dir.absolute())
    last_prune = _LAST_PRUNE_TIMES.get(cache_key)
    if (
        not force
        and last_prune is not None
        and now - last_prune < config.prune_interval_seconds
    ):
        return None

    if not _PRUNE_LOCK.acquire(blocking=False):
        return None

    try:
        last_prune = _LAST_PRUNE_TIMES.get(cache_key)
        if (
            not force
            and last_prune is not None
            and now - last_prune < config.prune_interval_seconds
        ):
            return None

        stats = prune_cache(config=config)
        _LAST_PRUNE_TIMES[cache_key] = now
        return stats
    except Exception:  # noqa: BLE001 - pruning must never break cache users.
        _LAST_PRUNE_TIMES[cache_key] = now
        LOGGER.warning("Cache pruning failed", exc_info=True)
        return None
    finally:
        _PRUNE_LOCK.release()


def prune_cache_on_startup() -> CachePruneStats | None:
    config = get_cache_prune_config()
    if not config.prune_on_start:
        return None
    return maybe_prune_cache(root_dir=config.root_dir, force=True)


def clear_cache(
    *,
    namespace: str,
    confirm: bool,
    root_dir: Path | None = None,
) -> CacheClearStats:
    if namespace not in {*CACHE_NAMESPACES, "all"}:
        return CacheClearStats(
            namespace=namespace,
            deleted_files=0,
            deleted_bytes=0,
            error="namespace must be search, fetch, or all",
        )
    if not confirm:
        return CacheClearStats(
            namespace=namespace,
            deleted_files=0,
            deleted_bytes=0,
            error="confirm must be true to clear cache files",
        )

    root = root_dir or get_cache_dir()
    _ensure_cache_namespace_dirs(root)
    target_namespaces = CACHE_NAMESPACES if namespace == "all" else (namespace,)
    deleted_files = 0
    deleted_bytes = 0

    for cache_file in _iter_cache_files(root):
        if cache_file.namespace not in target_namespaces:
            continue
        if _delete_cache_file(cache_file.path):
            deleted_files += 1
            deleted_bytes += cache_file.size

    return CacheClearStats(
        namespace=namespace,
        deleted_files=deleted_files,
        deleted_bytes=deleted_bytes,
    )


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
        maybe_prune_cache(root_dir=self.root_dir)
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
        maybe_prune_cache(root_dir=self.root_dir)
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
