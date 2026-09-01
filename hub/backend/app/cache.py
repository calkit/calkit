"""A cache shared by every worker.

Almost everything the project view shows is derived from one commit: the
pipeline and its stage statuses, the figures, the parsed publications. That
makes it cacheable in the strongest sense -- keyed by the commit SHA it was
computed from, an entry is never stale, only unused. What it is not is
cheap: recomputing a stage status walks object storage, and the API runs
eight workers, so a cache living inside one process is cold seven times out
of eight.

This module is that cache, backed by Redis. It is optional by design: with
``REDIS_URL`` unset, or with Redis down, every read misses and every write
is dropped, so the only thing lost is the speed-up. Callers therefore never
need to handle a cache failure, and a cache outage cannot take the API with
it.
"""

import json
import threading
from typing import Any

from app.config import settings
from app.core import logger

_client: Any = None
_client_lock = threading.Lock()
_client_ready = False
# Flipped after the first failure so a Redis outage logs once per worker
# rather than once per request.
_warned = False


def get_client() -> Any:
    """The shared Redis client, or None when caching is not configured."""
    global _client, _client_ready
    if _client_ready:
        return _client
    with _client_lock:
        if _client_ready:
            return _client
        if settings.REDIS_URL:
            try:
                import redis

                _client = redis.Redis.from_url(
                    settings.REDIS_URL,
                    socket_timeout=1,
                    socket_connect_timeout=1,
                    decode_responses=False,
                )
            except Exception as e:
                logger.warning(f"Could not create cache client: {e}")
                _client = None
        _client_ready = True
        return _client


def _warn_once(message: str) -> None:
    global _warned
    if not _warned:
        _warned = True
        logger.warning(message)


def get_json(key: str) -> Any | None:
    """The value stored at ``key``, or None if there isn't one."""
    client = get_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception as e:
        _warn_once(f"Cache read failed, continuing without it: {e}")
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as e:
        # A value we can't read is a value we shouldn't keep.
        logger.warning(f"Discarding unreadable cache entry {key}: {e}")
        try:
            client.delete(key)
        except Exception:
            pass
        return None


def set_json(key: str, value: Any, ttl: int | None = None) -> None:
    """Store ``value`` at ``key``. Failures are logged, never raised."""
    client = get_client()
    if client is None:
        return
    try:
        client.set(
            key,
            json.dumps(value).encode(),
            ex=ttl if ttl is not None else settings.CACHE_TTL_S,
        )
    except Exception as e:
        _warn_once(f"Cache write failed, continuing without it: {e}")


def make_key(*parts: str) -> str:
    """A cache key from its parts, namespaced by environment.

    Staging and production share a Redis in some deployments, and the same
    project can sit at the same commit in both, so the environment has to be
    part of the key or one would answer for the other.
    """
    return ":".join(["ck", settings.ENVIRONMENT, *parts])
