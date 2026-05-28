"""The REST API client."""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from functools import partial
from typing import Literal

import requests
from requests.exceptions import HTTPError

from . import config

logger = logging.getLogger(__name__)

# A dictionary of tokens keyed by base URL
_tokens = {}

# Single lock guarding all token-refresh operations to prevent thundering herds
# (e.g., many concurrent fsspec threads all attempting to refresh at once).
_refresh_lock = threading.Lock()

# Seconds before JWT expiry at which we proactively refresh.
_REFRESH_BUFFER_SECONDS = 60

# Serializes interactive device-login attempts so that, when several
# concurrent requests all hit an auth failure, only one of them actually
# prompts the user; the rest wait on the lock and then reuse the freshly
# minted token. The device-flow's own polling calls use ``auth=False`` so
# they don't recurse into the auth-retry paths in ``_request``.
_device_login_lock = threading.Lock()


class DeviceLoginError(RuntimeError):
    """Raised when the OAuth device login flow cannot complete."""


def run_device_flow() -> str:
    """Run the OAuth device login flow and return the new access token.

    On success the token is written to the config file and the in-memory
    token cache. Raises :class:`DeviceLoginError` on any failure (server
    error, expired/missing device code, timeout, etc.).
    """
    # Serialize concurrent attempts (e.g. multiple fsspec threads all hitting
    # 403 at the same time): the first thread runs the flow, the rest wait
    # and then reuse the freshly minted token.
    base_url = get_base_url()
    token_before = _tokens.get(base_url)
    with _device_login_lock:
        token_after = _tokens.get(base_url)
        # If the cached token changed while we were waiting on the lock,
        # another thread just completed a device flow — reuse its result.
        if token_after is not None and token_after != token_before:
            return token_after
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = None
        print("Initiating device login flow", flush=True)
        try:
            resp = post(
                "/login/device",
                json={"hostname": hostname},
                auth=False,
            )
            device_code = resp["device_code"]
            verification_uri = resp["verification_uri"]
            expires_in = int(resp["expires_in"])
            interval = int(resp["interval"])
        except Exception as e:
            raise DeviceLoginError(
                f"Failed to initiate device login flow: {e}"
            ) from e
        print("Authorize this device by opening this URL:", flush=True)
        print(verification_uri, flush=True)
        print("Waiting for authorization", flush=True)
        try:
            webbrowser.open(verification_uri)
        except Exception:
            pass
        deadline = time.monotonic() + expires_in
        while time.monotonic() < deadline:
            try:
                token_resp = post(
                    "/login/device/token",
                    json={"device_code": device_code},
                    auth=False,
                )
            except Exception as e:
                txt = str(e)
                if "Device code has expired" in txt:
                    raise DeviceLoginError(
                        "Device code has expired; "
                        "Run 'calkit cloud login' again"
                    ) from e
                if "Device code not found" in txt:
                    raise DeviceLoginError(
                        "Device code not found; "
                        "Run 'calkit cloud login' again"
                    ) from e
                raise DeviceLoginError(
                    f"Error while polling for device authorization: {e}"
                ) from e
            access_token = token_resp.get("access_token")
            if access_token:
                refresh_token = token_resp.get("refresh_token")
                try:
                    cfg = config.read()
                    cfg.access_token = access_token
                    if refresh_token:
                        cfg.refresh_token = refresh_token
                    # A stored PAT (``token``) takes priority over
                    # ``access_token`` in get_token(), so a stale PAT would
                    # keep being used by future processes and re-trigger
                    # the device flow every time. The user just
                    # re-authenticated, so device-flow credentials win.
                    if getattr(cfg, "token", None) is not None:
                        cfg.token = None
                    # A stored DVC token may have been revoked alongside
                    # the access token that just failed; clear it so the
                    # next remote-auth check mints a fresh one.
                    if getattr(cfg, "dvc_token", None) is not None:
                        cfg.dvc_token = None
                    cfg.write()
                    _tokens[base_url] = access_token
                except Exception as e:
                    raise DeviceLoginError(
                        f"Failed to save token in config: {e}"
                    ) from e
                print("Logged in successfully ✅", flush=True)
                return access_token
            sleep_seconds = min(
                interval, max(0.0, deadline - time.monotonic())
            )
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        raise DeviceLoginError(
            "Timed out waiting for device authorization; "
            "Run 'calkit cloud login' again"
        )


def get_base_url() -> str:
    """Get the API base URL."""
    override = os.environ.get("CALKIT_CLOUD_BASE_URL")
    if override:
        return override
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
    device_login_attempted = False
    # We may prompt the user via the device login flow only when stdin and
    # stdout are TTYs (i.e. not in CI, daemons, or piped subprocesses) and
    # the user hasn't opted out via the env var.
    can_prompt = auth and not os.environ.get("CALKIT_NO_INTERACTIVE_LOGIN")
    if can_prompt:
        try:
            can_prompt = sys.stdin.isatty() and sys.stdout.isatty()
        except Exception:
            can_prompt = False
    for retry_num in range(max_retries + 1):
        try:
            req_headers = get_headers(headers, auth=auth)
        except ValueError:
            # No token in config at all. If we can prompt the user, run
            # the device flow and try again; otherwise re-raise so callers
            # see the original "no token" error. ``run_device_flow``
            # serializes concurrent callers via ``_device_login_lock`` and
            # reuses the freshly minted token, so threads that arrive
            # mid-flow simply wait their turn rather than re-prompting.
            if can_prompt and not device_login_attempted:
                device_login_attempted = True
                run_device_flow()
                continue
            raise
        resp = func(
            base_url + path,
            params=params,
            json=json,
            data=data,
            headers=req_headers,
            **kwargs,
        )
        if resp.status_code == 502 and retry_num < max_retries:
            wait = min(base_delay_seconds * (2**retry_num), max_delay_seconds)
            time.sleep(wait)
            continue
        # Decide whether this response is a credential rejection (vs. a
        # permission/authorization failure that happens to also be 403).
        # 401 is always a credential rejection. For 403, only treat it as
        # one if the API's ``detail`` identifies it as such — otherwise
        # we'd hijack legitimate "you can't do that" errors and pop a
        # browser-based login flow at the user.
        looks_like_auth_failure = auth and resp.status_code == 401
        if auth and resp.status_code == 403:
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = None
            looks_like_auth_failure = isinstance(detail, str) and any(
                s in detail
                for s in (
                    "Could not validate credentials",
                    "Not authenticated",
                    "Invalid token",
                    "Token has expired",
                )
            )
        # On credential rejection, attempt a token refresh once.
        # ``_try_refresh`` returns ``None`` when no refresh token is stored
        # (e.g. PAT-only sessions). ``get_headers()`` re-calls
        # ``get_token()`` on the next iteration, so it will automatically
        # pick up the new token stored in ``_tokens`` by ``_try_refresh``.
        if looks_like_auth_failure and not refresh_attempted:
            refresh_attempted = True
            new_token = _try_refresh()
            if new_token is not None:
                continue
        # If refresh didn't help, fall back to the interactive device login
        # flow once. This covers both HTTP remotes (where /user/tokens
        # 401/403s) and ck:// remotes (which go through this same
        # ``_request`` path). ``run_device_flow`` serializes via
        # ``_device_login_lock`` and reuses the new token, so concurrent
        # callers wait rather than each starting their own flow.
        if (
            looks_like_auth_failure
            and can_prompt
            and not device_login_attempted
        ):
            device_login_attempted = True
            try:
                run_device_flow()
            except DeviceLoginError as e:
                logger.warning("Device login failed: %s", e)
            else:
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
