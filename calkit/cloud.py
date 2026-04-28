"""The REST API client."""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from functools import partial
from typing import Literal

import requests
from requests.exceptions import HTTPError

from . import config

logger = logging.getLogger(__name__)

# A dictionary of tokens keyed by base URL
_tokens = {}

# Single lock guarding all token-refresh operations to prevent thundering herds
# (e.g. many concurrent fsspec threads all attempting to refresh at once).
_refresh_lock = threading.Lock()

# Seconds before JWT expiry at which we proactively refresh.
_REFRESH_BUFFER_SECONDS = 60


def get_base_url() -> str:
    """Get the API base URL."""
    urls = {
        "local": "http://api.localhost",
        "staging": "https://api.staging.calkit.io",
        "production": "https://api.calkit.io",
        "test": "http://api.localhost",
    }
    return urls[config.get_env()]


def _jwt_exp(token: str) -> float | None:
    """Return the ``exp`` claim of a JWT as a UTC timestamp, or ``None``.

    Does not verify the signature — only used for proactive expiry checks.
    """
    try:
        # JWTs are <header>.<payload>.<sig>, all base64url-encoded
        payload_b64 = token.split(".")[1]
        # Pad to a multiple of 4 for standard base64 decoding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(payload["exp"])
    except Exception:
        return None


def _token_is_expiring(token: str) -> bool:
    """Return True if ``token`` is a JWT that expires within the refresh
    buffer.
    """
    exp = _jwt_exp(token)
    if exp is None:
        return False  # Not a JWT (e.g. a PAT) — never proactively refresh
    return time.time() >= exp - _REFRESH_BUFFER_SECONDS


def get_token() -> str:
    """Return a valid bearer token.

    Priority: in-memory cache (refreshed proactively if expiring), then PAT
    (``token`` / ``CALKIT_TOKEN`` env var), then short-lived ``access_token``
    from device login.

    For access tokens, expiry is read from the JWT ``exp`` claim and a refresh
    is attempted before the token expires.  Only one thread performs the
    refresh at a time; all others wait behind ``_refresh_lock`` and then use
    the new token that was stored in the cache.
    """
    base_url = get_base_url()
    cached = _tokens.get(base_url)
    if cached is not None and not _token_is_expiring(cached):
        return cached
    # Token missing or expiring — acquire the lock so only one thread refreshes
    with _refresh_lock:
        # Re-check after acquiring lock; another thread may have refreshed
        cached = _tokens.get(base_url)
        if cached is not None and not _token_is_expiring(cached):
            return cached
        # If we have a refresh token, try to get a new access token now
        if cached is not None and _token_is_expiring(cached):
            new_token = _do_refresh()
            if new_token is not None:
                return new_token
        # No usable cached token — load from config
        cfg = config.read()
        # Prefer long-lived PAT if present (env var CALKIT_TOKEN or config)
        if cfg.token is not None:
            _tokens[base_url] = cfg.token
            return cfg.token
        # Fall back to short-lived access token from device login
        if cfg.access_token is not None:
            if not _token_is_expiring(cfg.access_token):
                _tokens[base_url] = cfg.access_token
                return cfg.access_token
            # Config token is also expiring — attempt refresh
            new_token = _do_refresh()
            if new_token is not None:
                return new_token
        raise ValueError(
            "No token found; Run 'calkit cloud login' to authenticate"
        )


def _do_refresh() -> str | None:
    """Perform a token refresh request.

    Must be called with ``_refresh_lock`` already held (or from within
    ``_try_refresh`` which acquires it).  Returns the new access token on
    success or ``None`` on failure.
    """
    cfg = config.read()
    if cfg.refresh_token is None:
        return None
    base_url = get_base_url()
    try:
        resp = requests.post(
            base_url + "/login/refresh",
            json={"refresh_token": cfg.refresh_token},
        )
        resp.raise_for_status()
        data = resp.json()
        new_access = data["access_token"]
        new_refresh = data.get("refresh_token", cfg.refresh_token)
        cfg.access_token = new_access
        cfg.refresh_token = new_refresh
        cfg.write()
        _tokens[base_url] = new_access
        return new_access
    except Exception as exc:
        logger.debug("Token refresh failed: %s", exc)
        return None


def _try_refresh() -> str | None:
    """Attempt a token refresh from outside the normal request cycle.

    Acquires ``_refresh_lock`` to prevent concurrent refresh storms.
    Returns the new access token on success, or ``None``.
    """
    with _refresh_lock:
        return _do_refresh()


def get_headers(headers: dict | None = None, auth: bool = True) -> dict:
    if auth:
        base_headers = {"Authorization": f"Bearer {get_token()}"}
    else:
        base_headers = {}
    if headers is not None:
        return base_headers | headers
    else:
        return base_headers


def _request(
    kind: Literal["get", "post", "put", "patch", "delete"],
    path: str,
    params: dict | None = None,
    json: dict | None = None,
    data: dict | None = None,
    headers: dict | None = None,
    as_json=True,
    auth: bool = True,
    base_url: str | None = None,
    **kwargs,
):
    max_retries = 10
    base_delay_seconds = 0.25
    max_delay_seconds = 30
    func = getattr(requests, kind)
    if base_url is None:
        base_url = get_base_url()
    refresh_attempted = False
    for retry_num in range(max_retries + 1):
        resp = func(
            base_url + path,
            params=params,
            json=json,
            data=data,
            headers=get_headers(headers, auth=auth),
            **kwargs,
        )
        if resp.status_code == 502 and retry_num < max_retries:
            wait = min(base_delay_seconds * (2**retry_num), max_delay_seconds)
            time.sleep(wait)
            continue
        # On 401, attempt a token refresh once (only for access_token sessions,
        # not PATs — _try_refresh returns None when no refresh_token is stored).
        # get_headers() re-calls get_token() on the next iteration, so it will
        # automatically pick up the new token stored in _tokens by _try_refresh.
        if resp.status_code == 401 and auth and not refresh_attempted:
            refresh_attempted = True
            new_token = _try_refresh()
            if new_token is not None:
                continue
        try:
            resp.raise_for_status()
        except HTTPError as e:
            try:
                detail = resp.json()["detail"]
            except Exception:
                raise e
            raise HTTPError(f"{resp.status_code}: {detail}")
        break
    if as_json:
        return resp.json()
    else:
        return resp


get = partial(_request, "get")
post = partial(_request, "post")
patch = partial(_request, "patch")
put = partial(_request, "put")
delete = partial(_request, "delete")


def get_current_user() -> dict:
    return get("/user")
