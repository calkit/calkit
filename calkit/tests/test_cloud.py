"""Unit tests for calkit.cloud token management."""

from __future__ import annotations

import base64
import json
import threading
import time

import pytest

import calkit.cloud as cloud


def test_get_base_url_env_override(monkeypatch):
    monkeypatch.setenv("CALKIT_CLOUD_BASE_URL", "http://localhost:9999")
    assert cloud.get_base_url() == "http://localhost:9999"


def test_get_base_url_no_override(monkeypatch):
    monkeypatch.delenv("CALKIT_CLOUD_BASE_URL", raising=False)
    # Should return the test-env URL (CALKIT_ENV=test is set by pytest config)
    url = cloud.get_base_url()
    assert url.startswith("http")


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
    assert cloud._jwt_exp(token) == pytest.approx(exp, abs=1)


def test_jwt_exp_returns_none_for_opaque_token():
    assert cloud._jwt_exp("ckp_someopaquesecret") is None


def test_jwt_exp_returns_none_for_malformed():
    # Too many segments — payload is not valid JSON
    assert cloud._jwt_exp("not.a.jwt.at.all.with.too.many.parts") is None
    # No dots at all — split(".")[1] raises IndexError, caught → None
    assert cloud._jwt_exp("notajwt") is None


def test_token_is_expiring_false_when_far_in_future():
    token = _make_jwt(time.time() + 3600)
    assert cloud._token_is_expiring(token) is False


def test_token_is_expiring_true_when_within_buffer():
    token = _make_jwt(time.time() + cloud._REFRESH_BUFFER_SECONDS - 1)
    assert cloud._token_is_expiring(token) is True


def test_token_is_expiring_false_for_pat():
    # Opaque PATs have no exp claim — should never be considered expiring
    assert cloud._token_is_expiring("ckp_someopaquesecret") is False


def test_get_token_returns_cached_pat(monkeypatch):
    base_url = cloud.get_base_url()
    monkeypatch.setitem(cloud._tokens, base_url, "pat-token")
    assert cloud.get_token() == "pat-token"


def test_get_token_proactively_refreshes_expiring_jwt(monkeypatch):
    base_url = cloud.get_base_url()
    expiring = _make_jwt(time.time() + 10)  # within buffer
    monkeypatch.setitem(cloud._tokens, base_url, expiring)

    class DummyCfg:
        token = None
        access_token = expiring
        refresh_token = "ref-tok"

        def write(self):
            pass

    fresh = _make_jwt(time.time() + 3600)

    def _fake_do_refresh():
        cloud._tokens[base_url] = fresh
        return fresh

    monkeypatch.setattr(cloud, "_do_refresh", _fake_do_refresh)
    monkeypatch.setattr(cloud.config, "read", lambda: DummyCfg())
    assert cloud.get_token() == fresh


def test_get_token_falls_back_to_pat_in_config(monkeypatch):
    base_url = cloud.get_base_url()
    monkeypatch.setitem(cloud._tokens, base_url, None)
    # Ensure the None entry is actually absent so the cache miss path runs
    del cloud._tokens[base_url]

    class DummyCfg:
        token = "my-pat"
        access_token = None
        refresh_token = None

        def write(self):
            pass

    monkeypatch.setattr(cloud.config, "read", lambda: DummyCfg())
    assert cloud.get_token() == "my-pat"
    assert cloud._tokens[base_url] == "my-pat"


def test_get_token_raises_when_no_credentials(monkeypatch):
    base_url = cloud.get_base_url()
    cloud._tokens.pop(base_url, None)

    class DummyCfg:
        token = None
        access_token = None
        refresh_token = None

        def write(self):
            pass

    monkeypatch.setattr(cloud.config, "read", lambda: DummyCfg())
    with pytest.raises(ValueError, match="calkit cloud login"):
        cloud.get_token()


def test_do_refresh_returns_new_token(monkeypatch):
    base_url = cloud.get_base_url()

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

    monkeypatch.setattr(cloud.config, "read", lambda: DummyCfg())
    monkeypatch.setattr(cloud.requests, "post", lambda *_a, **_kw: DummyResp())
    with cloud._refresh_lock:
        result = cloud._do_refresh()
    assert result == fresh
    assert cloud._tokens[base_url] == fresh


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

    monkeypatch.setattr(cloud.config, "read", lambda: DummyCfg())
    monkeypatch.setattr(cloud.requests, "post", lambda *_a, **_kw: FailResp())
    with cloud._refresh_lock:
        result = cloud._do_refresh()
    assert result is None


def test_do_refresh_returns_none_when_no_refresh_token(monkeypatch):
    class DummyCfg:
        refresh_token = None
        access_token = None

        def write(self):
            pass

    monkeypatch.setattr(cloud.config, "read", lambda: DummyCfg())
    with cloud._refresh_lock:
        result = cloud._do_refresh()
    assert result is None


def test_request_retries_on_401_with_refresh(monkeypatch):
    base_url = cloud.get_base_url()
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

    monkeypatch.setattr(cloud.requests, "get", _fake_get)
    monkeypatch.setitem(cloud._tokens, base_url, fresh)
    monkeypatch.setattr(cloud, "_try_refresh", lambda: fresh)
    result = cloud._request("get", "/test", base_url=base_url)
    assert result == {"ok": True}
    assert call_count["n"] == 2


def test_concurrent_refresh_fires_only_once(monkeypatch):
    """Many threads calling get_token() on an expiring JWT should trigger
    exactly one refresh request, not one per thread."""
    base_url = cloud.get_base_url()
    expiring = _make_jwt(time.time() + 10)
    cloud._tokens[base_url] = expiring
    refresh_call_count = {"n": 0}
    fresh = _make_jwt(time.time() + 3600)

    def _fake_do_refresh():
        refresh_call_count["n"] += 1
        time.sleep(0.02)  # simulate network latency
        cloud._tokens[base_url] = fresh
        return fresh

    class DummyCfg:
        token = None
        access_token = expiring
        refresh_token = "ref"

        def write(self):
            pass

    monkeypatch.setattr(cloud, "_do_refresh", _fake_do_refresh)
    monkeypatch.setattr(cloud.config, "read", lambda: DummyCfg())
    results = []

    def _worker():
        results.append(cloud.get_token())

    threads = [threading.Thread(target=_worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert refresh_call_count["n"] == 1
    assert all(r == fresh for r in results)
