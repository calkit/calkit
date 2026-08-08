"""Unit tests for calkit.hub token management."""

from __future__ import annotations

import base64
import json
import threading
import time

import pytest

import calkit.hub as hub


def test_get_base_url_env_override(monkeypatch):
    monkeypatch.delenv("CALKIT_CLOUD_BASE_URL", raising=False)
    monkeypatch.setenv("CALKIT_HUB_API_BASE_URL", "http://localhost:9999")
    assert hub.get_base_url() == "http://localhost:9999"
    # The old name still works, so existing setups don't break
    monkeypatch.delenv("CALKIT_HUB_API_BASE_URL")
    monkeypatch.setenv("CALKIT_CLOUD_BASE_URL", "http://localhost:8888")
    assert hub.get_base_url() == "http://localhost:8888"
    # ...but the new one wins when both are set
    monkeypatch.setenv("CALKIT_HUB_API_BASE_URL", "http://localhost:9999")
    assert hub.get_base_url() == "http://localhost:9999"


def test_get_base_url_no_override(monkeypatch):
    monkeypatch.delenv("CALKIT_HUB_API_BASE_URL", raising=False)
    monkeypatch.delenv("CALKIT_CLOUD_BASE_URL", raising=False)
    # CALKIT_ENV=test is set by pytest config → should return the test-env URL
    assert hub.get_base_url() == "http://api.localhost"


def test_hub_urls(monkeypatch):
    # CALKIT_ENV=test is set by pytest config → the local dev web app URL
    assert hub.get_hub_url() == "http://localhost:5173"
    monkeypatch.setenv("CALKIT_HUB", "calkit.io")
    assert hub.get_hub_url() == "https://calkit.io"
    # Known hub URLs map back to their environment names, tolerating a
    # trailing slash; arbitrary hubs are not yet resolvable
    assert hub.env_for_hub("https://calkit.io") == "production"
    assert hub.env_for_hub("https://calkit.io/") == "production"
    assert hub.env_for_hub("https://staging.calkit.io") == "staging"
    assert hub.env_for_hub("http://localhost:5173") == "local"
    assert hub.env_for_hub("https://other-calkit.io") is None


def test_api_url_from_hub_url(monkeypatch):
    # A hub's API lives on the api subdomain of its host, so its URL is all
    # that's needed to reach it
    assert (
        hub.api_url_from_hub_url("https://calkit.example.edu")
        == "https://api.calkit.example.edu"
    )
    # A missing scheme is filled in, https for a real host
    assert (
        hub.api_url_from_hub_url("calkit.example.edu")
        == "https://api.calkit.example.edu"
    )
    # A trailing slash and a path don't change the host
    assert (
        hub.api_url_from_hub_url("https://calkit.example.edu/")
        == "https://api.calkit.example.edu"
    )
    # A port is carried over, and a local host stays on http
    assert (
        hub.api_url_from_hub_url("http://localhost:8000")
        == "http://api.localhost:8000"
    )
    # A URL that already names the API host is left alone rather than
    # picking up a second prefix
    assert (
        hub.api_url_from_hub_url("https://api.calkit.example.edu")
        == "https://api.calkit.example.edu"
    )
    with pytest.raises(ValueError):
        hub.api_url_from_hub_url("https://")
    # An arbitrary hub resolves through the rule, while the built-in
    # environments keep their explicitly declared URLs
    monkeypatch.delenv("CALKIT_HUB_API_BASE_URL", raising=False)
    monkeypatch.delenv("CALKIT_CLOUD_BASE_URL", raising=False)
    monkeypatch.delenv("CALKIT_ENV", raising=False)
    monkeypatch.setenv("CALKIT_HUB", "https://calkit.example.edu")
    assert hub.get_base_url() == "https://api.calkit.example.edu"
    monkeypatch.setenv("CALKIT_HUB", "calkit.io")
    assert hub.get_base_url() == "https://api.calkit.io"


def _make_jwt(exp: float) -> str:
    """Build a minimal unsigned JWT with the given ``exp`` claim."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "test", "exp": exp}).encode()
    ).rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.fakesig"


def test_jwt_exp_extracts_claim():
    exp = time.time() + 3600
    token = _make_jwt(exp)
    assert hub._jwt_exp(token) == pytest.approx(exp, abs=1)


def test_jwt_exp_returns_none_for_opaque_token():
    assert hub._jwt_exp("ckp_someopaquesecret") is None


def test_jwt_exp_returns_none_for_malformed():
    # Too many segments — payload is not valid JSON
    assert hub._jwt_exp("not.a.jwt.at.all.with.too.many.parts") is None
    # No dots at all — split(".")[1] raises IndexError, caught → None
    assert hub._jwt_exp("notajwt") is None


def test_token_is_expiring_false_when_far_in_future():
    token = _make_jwt(time.time() + 3600)
    assert hub._token_is_expiring(token) is False


def test_token_is_expiring_true_when_within_buffer():
    token = _make_jwt(time.time() + hub._REFRESH_BUFFER_SECONDS - 1)
    assert hub._token_is_expiring(token) is True


def test_token_is_expiring_false_for_pat():
    # Opaque PATs have no exp claim — should never be considered expiring
    assert hub._token_is_expiring("ckp_someopaquesecret") is False


def test_get_token_returns_cached_pat(monkeypatch):
    base_url = hub.get_base_url()
    monkeypatch.setitem(hub._tokens, base_url, "pat-token")
    assert hub.get_token() == "pat-token"


def test_get_token_proactively_refreshes_expiring_jwt(monkeypatch):
    base_url = hub.get_base_url()
    expiring = _make_jwt(time.time() + 10)  # within buffer
    monkeypatch.setitem(hub._tokens, base_url, expiring)

    class DummyCfg:
        token = None
        access_token = expiring
        refresh_token = "ref-tok"

        def write(self):
            pass

    fresh = _make_jwt(time.time() + 3600)

    def _fake_do_refresh():
        hub._tokens[base_url] = fresh
        return fresh

    monkeypatch.setattr(hub, "_do_refresh", _fake_do_refresh)
    monkeypatch.setattr(hub.config, "read", lambda: DummyCfg())
    assert hub.get_token() == fresh


def test_get_token_falls_back_to_pat_in_config(monkeypatch):
    base_url = hub.get_base_url()
    monkeypatch.setitem(hub._tokens, base_url, None)
    # Ensure the None entry is actually absent so the cache miss path runs
    del hub._tokens[base_url]

    class DummyCfg:
        token = "my-pat"
        access_token = None
        refresh_token = None

        def write(self):
            pass

    monkeypatch.setattr(hub.config, "read", lambda: DummyCfg())
    assert hub.get_token() == "my-pat"
    assert hub._tokens[base_url] == "my-pat"


def test_get_token_raises_when_no_credentials(monkeypatch):
    base_url = hub.get_base_url()
    hub._tokens.pop(base_url, None)

    class DummyCfg:
        token = None
        access_token = None
        refresh_token = None

        def write(self):
            pass

    monkeypatch.setattr(hub.config, "read", lambda: DummyCfg())
    with pytest.raises(ValueError, match="calkit hub login"):
        hub.get_token()


def test_do_refresh_returns_new_token(monkeypatch):
    base_url = hub.get_base_url()

    class DummyCfg:
        refresh_token = "old-refresh"
        access_token = "old-access"

        def write(self):
            pass

    fresh = _make_jwt(time.time() + 3600)

    class DummyResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": fresh, "refresh_token": "new-refresh"}

    monkeypatch.setattr(hub.config, "read", lambda: DummyCfg())
    monkeypatch.setattr(hub.requests, "post", lambda *_a, **_kw: DummyResp())
    with hub._refresh_lock:
        result = hub._do_refresh()
    assert result == fresh
    assert hub._tokens[base_url] == fresh


def test_do_refresh_returns_none_on_http_error(monkeypatch):
    class DummyCfg:
        refresh_token = "old-refresh"
        access_token = "old-access"

        def write(self):
            pass

    class FailResp:
        status_code = 401

        def raise_for_status(self):
            raise Exception("401 Unauthorized")

        def json(self):
            return {}

    monkeypatch.setattr(hub.config, "read", lambda: DummyCfg())
    monkeypatch.setattr(hub.requests, "post", lambda *_a, **_kw: FailResp())
    with hub._refresh_lock:
        result = hub._do_refresh()
    assert result is None


def test_do_refresh_returns_none_when_no_refresh_token(monkeypatch):
    class DummyCfg:
        refresh_token = None
        access_token = None

        def write(self):
            pass

    monkeypatch.setattr(hub.config, "read", lambda: DummyCfg())
    with hub._refresh_lock:
        result = hub._do_refresh()
    assert result is None


def test_request_retries_on_401_with_refresh(monkeypatch):
    base_url = hub.get_base_url()
    fresh = _make_jwt(time.time() + 3600)
    call_count = {"n": 0}

    class Resp401:
        status_code = 401

        def raise_for_status(self):
            from requests.exceptions import HTTPError

            raise HTTPError("401")

        def json(self):
            return {"detail": "Unauthorized"}

    class Resp200:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def _fake_get(url, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return Resp401()
        return Resp200()

    monkeypatch.setattr(hub.requests, "get", _fake_get)
    monkeypatch.setitem(hub._tokens, base_url, fresh)
    monkeypatch.setattr(hub, "_try_refresh", lambda: fresh)
    result = hub._request("get", "/test", base_url=base_url)
    assert result == {"ok": True}
    assert call_count["n"] == 2


def test_request_invalid_credentials_403_triggers_refresh(monkeypatch):
    """A 403 whose detail says credentials are invalid should be treated
    like a 401 — refresh attempted, request retried."""
    base_url = hub.get_base_url()
    fresh = _make_jwt(time.time() + 3600)
    call_count = {"n": 0}

    class Resp403:
        status_code = 403

        def raise_for_status(self):
            from requests.exceptions import HTTPError

            raise HTTPError("403")

        def json(self):
            return {"detail": "Could not validate credentials"}

    class Resp200:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def _fake_get(url, **kwargs):
        call_count["n"] += 1
        return Resp403() if call_count["n"] == 1 else Resp200()

    monkeypatch.setattr(hub.requests, "get", _fake_get)
    monkeypatch.setitem(hub._tokens, base_url, fresh)
    monkeypatch.setattr(hub, "_try_refresh", lambda: fresh)
    result = hub._request("get", "/test", base_url=base_url)
    assert result == {"ok": True}
    assert call_count["n"] == 2


def test_request_permission_403_does_not_trigger_refresh(monkeypatch):
    """A 403 that's a real permission denial (e.g. user not allowed to
    create a project under an org) must surface as an HTTPError, not
    silently trigger refresh/device login."""
    base_url = hub.get_base_url()
    fresh = _make_jwt(time.time() + 3600)
    call_count = {"n": 0}
    refresh_calls = {"n": 0}

    class Resp403Perm:
        status_code = 403

        def raise_for_status(self):
            from requests.exceptions import HTTPError

            raise HTTPError("403")

        def json(self):
            return {"detail": "You are not allowed to create projects here"}

    def _fake_post(url, **kwargs):
        call_count["n"] += 1
        return Resp403Perm()

    def _fake_refresh():
        refresh_calls["n"] += 1
        return fresh

    monkeypatch.setattr(hub.requests, "post", _fake_post)
    monkeypatch.setitem(hub._tokens, base_url, fresh)
    monkeypatch.setattr(hub, "_try_refresh", _fake_refresh)
    with pytest.raises(Exception):
        hub._request("post", "/projects", base_url=base_url)
    assert call_count["n"] == 1
    assert refresh_calls["n"] == 0


def test_request_retries_on_transient_5xx(monkeypatch):
    """Transient 5xx responses are retried with backoff; a persistent 5xx
    eventually exhausts retries and surfaces as an HTTPError."""
    from requests.exceptions import HTTPError

    base_url = hub.get_base_url()
    fresh = _make_jwt(time.time() + 3600)
    monkeypatch.setitem(hub._tokens, base_url, fresh)
    # Avoid real sleeping during backoff.
    monkeypatch.setattr(hub.time, "sleep", lambda *_a, **_kw: None)

    class Resp:
        def __init__(self, status_code):
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise HTTPError(f"{self.status_code}")

        def json(self):
            return {"ok": True} if self.status_code < 400 else {}

    # Case 1: each transient 5xx status is retried once, then succeeds.
    for transient_status in (500, 502, 503, 504):
        statuses = [transient_status, 200]
        calls = {"n": 0}

        def _fake_get(url, **kwargs):
            status = statuses[calls["n"]]
            calls["n"] += 1
            return Resp(status)

        monkeypatch.setattr(hub.requests, "get", _fake_get)
        result = hub._request("get", "/test", base_url=base_url)
        assert result == {"ok": True}
        assert calls["n"] == 2
    # Case 2: a persistent 500 exhausts all retries and raises HTTPError.
    persistent = {"n": 0}

    def _fake_get_500(url, **kwargs):
        persistent["n"] += 1
        return Resp(500)

    monkeypatch.setattr(hub.requests, "get", _fake_get_500)
    with pytest.raises(HTTPError):
        hub._request("get", "/test", base_url=base_url)
    # Initial attempt plus max_retries follow-ups.
    assert persistent["n"] == 11


def test_request_retries_on_network_error(monkeypatch):
    """Transient network errors (read/connect timeout, connection reset) are
    retried; a persistent one eventually propagates."""
    from requests.exceptions import ConnectionError as ReqConnErr
    from requests.exceptions import Timeout

    base_url = hub.get_base_url()
    fresh = _make_jwt(time.time() + 3600)
    monkeypatch.setitem(hub._tokens, base_url, fresh)
    monkeypatch.setattr(hub.time, "sleep", lambda *_a, **_kw: None)

    class Resp200:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    # Case 1: two transient network errors, then success.
    errors = [Timeout("read timeout"), ReqConnErr("connection reset")]
    calls = {"n": 0}

    def _fake_get(url, **kwargs):
        calls["n"] += 1
        if calls["n"] <= len(errors):
            raise errors[calls["n"] - 1]
        return Resp200()

    monkeypatch.setattr(hub.requests, "get", _fake_get)
    assert hub._request("get", "/test", base_url=base_url) == {"ok": True}
    assert calls["n"] == 3
    # Case 2: a persistent network error exhausts retries and propagates.
    persistent = {"n": 0}

    def _always_timeout(url, **kwargs):
        persistent["n"] += 1
        raise Timeout("read timeout")

    monkeypatch.setattr(hub.requests, "get", _always_timeout)
    with pytest.raises(Timeout):
        hub._request("get", "/test", base_url=base_url)
    assert persistent["n"] == 11


def test_concurrent_refresh_fires_only_once(monkeypatch):
    """Many threads calling get_token() on an expiring JWT should trigger
    exactly one refresh request, not one per thread."""
    base_url = hub.get_base_url()
    expiring = _make_jwt(time.time() + 10)
    hub._tokens[base_url] = expiring
    refresh_call_count = {"n": 0}
    fresh = _make_jwt(time.time() + 3600)

    def _fake_do_refresh():
        refresh_call_count["n"] += 1
        time.sleep(0.02)  # simulate network latency
        hub._tokens[base_url] = fresh
        return fresh

    class DummyCfg:
        token = None
        access_token = expiring
        refresh_token = "ref"

        def write(self):
            pass

    monkeypatch.setattr(hub, "_do_refresh", _fake_do_refresh)
    monkeypatch.setattr(hub.config, "read", lambda: DummyCfg())
    results = []

    def _worker():
        results.append(hub.get_token())

    threads = [threading.Thread(target=_worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert refresh_call_count["n"] == 1
    assert all(r == fresh for r in results)
