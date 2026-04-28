"""Tests for the cloud CLI."""

import pytest
import typer
from requests.exceptions import HTTPError

import calkit.cli.cloud as cloud_cli


def test_cloud_login_already_logged_in(monkeypatch, capsys):
    def _get(path):
        assert path == "/user"
        return {"email": "user@example.com"}

    monkeypatch.setattr(cloud_cli.calkit.cloud, "get", _get)
    cloud_cli.login()
    out = capsys.readouterr().out
    assert "Authenticated successfully" in out


def test_cloud_login_device_flow_success(monkeypatch, capsys):
    call_counts = {"token_polls": 0}
    post_calls = []

    class DummyConfig:
        def __init__(self):
            self.token = None
            self.access_token = None
            self.refresh_token = None
            self.written = False

        def write(self):
            self.written = True

    cfg = DummyConfig()

    def _get(path):
        assert path == "/user"
        raise HTTPError("401: Not authenticated")

    def _post(path, **kwargs):
        post_calls.append((path, kwargs))
        if path == "/login/device":
            return {
                "device_code": "dev-123",
                "verification_uri": (
                    "https://app.example.com/cli-auth?device_code=dev-123"
                ),
                "expires_in": 60,
                "interval": 1,
            }
        if path == "/login/device/token":
            call_counts["token_polls"] += 1
            if call_counts["token_polls"] < 2:
                return {"detail": "Authorization pending"}
            return {
                "access_token": "ckp_test_access",
                "refresh_token": "ckp_test_refresh",
            }
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(cloud_cli.calkit.cloud, "get", _get)
    monkeypatch.setattr(cloud_cli.calkit.cloud, "post", _post)
    monkeypatch.setattr(cloud_cli.calkit.config, "read", lambda: cfg)
    monkeypatch.setattr(cloud_cli.webbrowser, "open", lambda _url: True)
    monkeypatch.setattr(cloud_cli.time, "sleep", lambda _seconds: None)
    cloud_cli.login()
    out = capsys.readouterr().out
    assert "Authorize this device by opening this URL:" in out
    assert "Waiting for authorization" in out
    assert "Logged in successfully" in out
    assert cfg.access_token == "ckp_test_access"
    assert cfg.refresh_token == "ckp_test_refresh"
    assert cfg.token is None  # PAT field must not be touched by device login
    assert cfg.written is True
    assert post_calls[0][0] == "/login/device"
    assert post_calls[0][1].get("auth") is False
    assert post_calls[1][0] == "/login/device/token"
    assert post_calls[1][1].get("auth") is False


def test_cloud_login_force_re_authenticates(monkeypatch, capsys):
    """--force should start the device flow even when already authenticated."""

    class DummyConfig:
        def __init__(self):
            self.token = None
            self.access_token = None
            self.refresh_token = None

        def write(self):
            pass

    cfg = DummyConfig()

    def _get(path):
        return {"email": "user@example.com"}

    def _post(path, **kwargs):
        if path == "/login/device":
            return {
                "device_code": "dev-force",
                "verification_uri": "https://example.com/auth",
                "expires_in": 60,
                "interval": 1,
            }
        if path == "/login/device/token":
            return {
                "access_token": "ckp_new_access",
                "refresh_token": "ckp_new_refresh",
            }
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(cloud_cli.calkit.cloud, "get", _get)
    monkeypatch.setattr(cloud_cli.calkit.cloud, "post", _post)
    monkeypatch.setattr(cloud_cli.calkit.config, "read", lambda: cfg)
    monkeypatch.setattr(cloud_cli.webbrowser, "open", lambda _url: True)
    monkeypatch.setattr(cloud_cli.time, "sleep", lambda _s: None)
    cloud_cli.login(force=True)
    out = capsys.readouterr().out
    assert "Logged in successfully" in out
    assert cfg.access_token == "ckp_new_access"


def test_cloud_login_device_code_expired(monkeypatch):
    """Expired device code during polling should raise Exit."""

    def _get(path):
        raise HTTPError("401: Not authenticated")

    def _post(path, **kwargs):
        if path == "/login/device":
            return {
                "device_code": "dev-exp",
                "verification_uri": "https://example.com/auth",
                "expires_in": 60,
                "interval": 1,
            }
        raise Exception("401: Device code has expired")

    monkeypatch.setattr(cloud_cli.calkit.cloud, "get", _get)
    monkeypatch.setattr(cloud_cli.calkit.cloud, "post", _post)
    monkeypatch.setattr(cloud_cli.webbrowser, "open", lambda _url: True)
    monkeypatch.setattr(cloud_cli.time, "sleep", lambda _s: None)
    with pytest.raises(typer.Exit):
        cloud_cli.login()


def test_cloud_login_device_code_not_found(monkeypatch):
    """Not-found device code during polling should raise Exit."""

    def _get(path):
        raise HTTPError("401: Not authenticated")

    def _post(path, **kwargs):
        if path == "/login/device":
            return {
                "device_code": "dev-nf",
                "verification_uri": "https://example.com/auth",
                "expires_in": 60,
                "interval": 1,
            }
        raise Exception("404: Device code not found")

    monkeypatch.setattr(cloud_cli.calkit.cloud, "get", _get)
    monkeypatch.setattr(cloud_cli.calkit.cloud, "post", _post)
    monkeypatch.setattr(cloud_cli.webbrowser, "open", lambda _url: True)
    monkeypatch.setattr(cloud_cli.time, "sleep", lambda _s: None)
    with pytest.raises(typer.Exit):
        cloud_cli.login()
