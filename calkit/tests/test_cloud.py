"""Unit tests for calkit.cloud token management."""

from __future__ import annotations

import base64
import json
import threading
import time

import pytest

import calkit.cloud as cloud


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
    assert cloud._jwt_exp("not.a.jwt.at.all.with.too.many.parts") is None


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
