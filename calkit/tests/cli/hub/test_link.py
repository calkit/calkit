"""Tests for ``calkit.cli.hub_link``."""

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from requests.exceptions import HTTPError
from typer.testing import CliRunner

from calkit.cli.hub import hub_app
from calkit.hub import link as hub_link


def test_link(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    monkeypatch.setattr(hub_link, "use_own_hub", lambda: "https://api.hub")

    def register():
        raise HTTPError("403: Verify your email first")

    monkeypatch.setattr(hub_link, "register", register)
    # A hub that needs the email verified first says where to do it
    result = CliRunner().invoke(hub_app, ["link", "install", "--no-service"])
    assert result.exit_code == 1
    assert "Verify your email" in result.output
    assert "/settings" in result.output
    # Other errors are passed along as they are
    monkeypatch.setattr(
        hub_link,
        "register",
        lambda: (_ for _ in ()).throw(HTTPError("500: Boom")),
    )
    result = CliRunner().invoke(hub_app, ["link", "install", "--no-service"])
    assert result.exit_code == 1
    assert "500: Boom" in result.output
    # One whose key the hub refused is revoked with its own token, in case
    # someone else holds it, and registered again
    hub_link.save_config(
        {
            "name": "box",
            "token": "ckm_old",
            "api_url": "https://api.hub",
            "key_rejected": True,
        }
    )
    revoked: list[dict] = []
    monkeypatch.setattr(hub_link, "revoke_self", revoked.append)
    monkeypatch.setattr(
        hub_link,
        "register",
        lambda: {"name": "box-2", "token": "ckm_new"},
    )
    monkeypatch.setattr(hub_link, "uninstall_service", lambda key=None: None)
    result = CliRunner().invoke(hub_app, ["link", "install", "--no-service"])
    assert result.exit_code == 0, result.output
    assert [cfg["token"] for cfg in revoked] == ["ckm_old"]
    assert "Registered machine 'box-2'" in result.output
    # One that's still registered is kept, which is checked with its own
    # token, e.g., on a machine linked over SSH that never logged in
    from calkit.hub import core as hub

    hub_link.save_config(
        {
            "id": "m1",
            "name": "box",
            "token": "ckm_m1",
            "api_url": "https://api.hub",
        }
    )
    asked: list[dict] = []

    def request(kind, path, **kwargs):
        asked.append(kwargs)
        assert (kind, path) == ("get", "/machines/self")
        return {"id": "m1"}

    monkeypatch.setattr(hub, "_request", request)
    result = CliRunner().invoke(hub_app, ["link", "install", "--no-service"])
    assert result.exit_code == 0, result.output
    assert "Machine 'box' is already registered" in result.output
    assert asked[0]["auth"] is False
    assert asked[0]["headers"] == {"Authorization": "Bearer ckm_m1"}
    # Sessions would be root shells, so it never runs as root, sudo or not
    if hasattr(os, "geteuid"):
        monkeypatch.setattr(hub_link.os, "geteuid", lambda: 0)
        for args in [["link", "install", "--no-service"], ["link", "start"]]:
            result = CliRunner().invoke(hub_app, args)
            assert result.exit_code == 1
            assert "root" in result.output


def test_uninstall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from calkit.hub import core as hub

    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    # Selecting a hub sets these, which the test puts back afterward
    monkeypatch.setenv("CALKIT_HUB", "https://calkit.io")
    monkeypatch.setattr(hub_link, "_hub_url", "https://calkit.io")
    monkeypatch.setattr(hub_link, "uninstall_service", lambda key=None: None)
    calls = []

    def request(kind: str, path: str, **kwargs: Any) -> None:
        calls.append((kind, path, kwargs))
        if fail:
            response = SimpleNamespace(status_code=401)
            raise HTTPError("401: Invalid token", response=response)

    monkeypatch.setattr(hub, "_request", request)
    # With the link's own token, so it works however the user signed in
    # here, and one already revoked counts as done
    for fail in [False, True]:
        hub_link.save_config(
            {
                "name": "box",
                "hub_url": "https://calkit.io",
                "token": "ckm_x",
                "api_url": "https://api.hub",
            }
        )
        result = CliRunner().invoke(hub_app, ["link", "uninstall"])
        assert result.exit_code == 0, result.output
        assert "Could not revoke" not in result.output
        assert not os.path.exists(hub_link.get_config_path())
        kind, path, kwargs = calls.pop()
        assert (kind, path) == ("delete", "/machines/self")
        assert kwargs["headers"] == {"Authorization": "Bearer ckm_x"}
        assert kwargs["base_url"] == "https://api.hub"


def test_stop_and_restart_every_hub(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    # Selecting a hub sets these, which the test puts back afterward
    monkeypatch.setenv("CALKIT_HUB", "https://calkit.io")
    monkeypatch.setattr(hub_link, "_hub_url", None)
    for url in ["https://calkit.io", "http://localhost"]:
        hub_link.select_hub(url)
        hub_link.save_config({"name": "box", "hub_url": url})
    restarted: list[str] = []

    def restart_service():
        if hub_link.get_hub_url() == "http://localhost" and fail:
            raise RuntimeError("Boom")
        restarted.append(hub_link.get_hub_url())

    monkeypatch.setattr(hub_link, "restart_service", restart_service)
    stopped: list[str] = []
    monkeypatch.setattr(
        hub_link,
        "set_service_running",
        lambda running: stopped.append(hub_link.get_hub_url()),
    )
    # Without --hub, every hub's link, each named
    fail = False
    result = CliRunner().invoke(hub_app, ["link", "restart"])
    assert result.exit_code == 0, result.output
    assert sorted(restarted) == ["http://localhost", "https://calkit.io"]
    assert "Restarted the link for http://localhost" in result.output
    # Options go after the subcommand, and on their own only show help
    restarted.clear()
    result = CliRunner().invoke(
        hub_app, ["link", "--hub", "https://calkit.io", "restart"]
    )
    assert result.exit_code != 0
    assert not restarted
    result = CliRunner().invoke(hub_app, ["link"])
    assert "install" in result.output and "uninstall" in result.output
    assert not restarted
    result = CliRunner().invoke(hub_app, ["link", "stop"])
    assert result.exit_code == 0
    assert sorted(stopped) == ["http://localhost", "https://calkit.io"]
    # With it, only that one
    restarted.clear()
    result = CliRunner().invoke(
        hub_app, ["link", "restart", "--hub", "https://calkit.io"]
    )
    assert restarted == ["https://calkit.io"]
    assert result.output.strip() == "Restarted the link"
    # One failing doesn't stop the others, but the command fails
    restarted.clear()
    fail = True
    result = CliRunner().invoke(hub_app, ["link", "restart"])
    assert result.exit_code == 1
    assert restarted == ["https://calkit.io"]
    assert "Boom" in result.output
