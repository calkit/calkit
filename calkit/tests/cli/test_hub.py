"""Tests for the hub CLI."""

import os

import pytest
import typer
from requests.exceptions import HTTPError

import calkit.cli.hub as hub_cli


def test_use_hub(monkeypatch, tmp_dir):
    # Monkeypatch CALKIT_ENV first so its original value is restored on
    # teardown even though config.set_env mutates os.environ directly
    monkeypatch.setenv("CALKIT_ENV", "test")
    # An environment alias is accepted directly
    hub_cli._use_hub("staging")
    assert os.environ["CALKIT_ENV"] == "staging"
    # A known hub URL resolves to its environment
    hub_cli._use_hub("https://calkit.io")
    assert os.environ["CALKIT_ENV"] == "production"
    # An unknown hub URL is an error until per-hub config exists
    with pytest.raises(typer.Exit):
        hub_cli._use_hub("https://other-calkit.io")
    # An explicitly set env is the source of truth when no option is passed
    monkeypatch.setenv("CALKIT_ENV", "test")
    hub_cli._use_hub(None)
    assert os.environ["CALKIT_ENV"] == "test"
    # With no env set, the project's declared hub picks the instance
    with open("calkit.yaml", "w") as f:
        f.write("hub: https://staging.calkit.io\n")
    monkeypatch.delenv("CALKIT_ENV", raising=False)
    hub_cli._use_hub(None)
    assert os.environ["CALKIT_ENV"] == "staging"
    # A declared hub the CLI can't resolve is an error
    with open("calkit.yaml", "w") as f:
        f.write("hub: https://other-calkit.io\n")
    monkeypatch.delenv("CALKIT_ENV", raising=False)
    with pytest.raises(typer.Exit):
        hub_cli._use_hub(None)
    # No option, no env, no declared hub → production default (no change)
    with open("calkit.yaml", "w") as f:
        f.write("title: T\n")
    monkeypatch.delenv("CALKIT_ENV", raising=False)
    hub_cli._use_hub(None)
    assert "CALKIT_ENV" not in os.environ


def test_cloud_login_already_logged_in(monkeypatch, capsys):
    def _get(path):
        assert path == "/user"
        return {"email": "user@example.com"}

    monkeypatch.setattr(hub_cli.calkit.hub, "get", _get)
    hub_cli.login()
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

    monkeypatch.setattr(hub_cli.calkit.hub, "get", _get)
    monkeypatch.setattr(hub_cli.calkit.hub, "post", _post)
    monkeypatch.setattr(hub_cli.calkit.config, "read", lambda: cfg)
    monkeypatch.setattr(
        hub_cli.calkit.hub.webbrowser, "open", lambda _url: True
    )
    monkeypatch.setattr(
        hub_cli.calkit.hub.time, "sleep", lambda _seconds: None
    )
    hub_cli.login()
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

    monkeypatch.setattr(hub_cli.calkit.hub, "get", _get)
    monkeypatch.setattr(hub_cli.calkit.hub, "post", _post)
    monkeypatch.setattr(hub_cli.calkit.config, "read", lambda: cfg)
    monkeypatch.setattr(
        hub_cli.calkit.hub.webbrowser, "open", lambda _url: True
    )
    monkeypatch.setattr(hub_cli.calkit.hub.time, "sleep", lambda _s: None)
    hub_cli.login(force=True)
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

    monkeypatch.setattr(hub_cli.calkit.hub, "get", _get)
    monkeypatch.setattr(hub_cli.calkit.hub, "post", _post)
    monkeypatch.setattr(
        hub_cli.calkit.hub.webbrowser, "open", lambda _url: True
    )
    monkeypatch.setattr(hub_cli.calkit.hub.time, "sleep", lambda _s: None)
    with pytest.raises(typer.Exit):
        hub_cli.login()


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

    monkeypatch.setattr(hub_cli.calkit.hub, "get", _get)
    monkeypatch.setattr(hub_cli.calkit.hub, "post", _post)
    monkeypatch.setattr(
        hub_cli.calkit.hub.webbrowser, "open", lambda _url: True
    )
    monkeypatch.setattr(hub_cli.calkit.hub.time, "sleep", lambda _s: None)
    with pytest.raises(typer.Exit):
        hub_cli.login()
