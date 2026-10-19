"""Tests for ``calkit.cli.operator``."""

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from requests.exceptions import HTTPError
from typer.testing import CliRunner

from calkit import operator
from calkit.cli.operator import operator_app


def test_install(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    monkeypatch.setattr(operator, "use_own_hub", lambda: "https://api.hub")

    def register():
        raise HTTPError("403: Verify your email first")

    monkeypatch.setattr(operator, "register", register)
    # A hub that needs the email verified first says where to do it
    result = CliRunner().invoke(operator_app, ["install", "--no-service"])
    assert result.exit_code == 1
    assert "Verify your email" in result.output
    assert "/settings" in result.output
    # Other errors are passed along as they are
    monkeypatch.setattr(
        operator,
        "register",
        lambda: (_ for _ in ()).throw(HTTPError("500: Boom")),
    )
    result = CliRunner().invoke(operator_app, ["install", "--no-service"])
    assert result.exit_code == 1
    assert "500: Boom" in result.output
    # One whose key the hub refused is revoked with its own token, in case
    # someone else holds it, and registered again
    operator.save_config(
        {
            "name": "box",
            "token": "cko_old",
            "api_url": "https://api.hub",
            "key_rejected": True,
        }
    )
    revoked: list[dict] = []
    monkeypatch.setattr(operator, "revoke_self", revoked.append)
    monkeypatch.setattr(
        operator,
        "register",
        lambda: {"name": "box-2", "token": "cko_new"},
    )
    monkeypatch.setattr(operator, "uninstall_service", lambda key=None: None)
    result = CliRunner().invoke(operator_app, ["install", "--no-service"])
    assert result.exit_code == 0, result.output
    assert [cfg["token"] for cfg in revoked] == ["cko_old"]
    assert "Registered Operator 'box-2'" in result.output
    # Sessions would be root shells, so it never runs as root, sudo or not
    if hasattr(os, "geteuid"):
        monkeypatch.setattr(operator.os, "geteuid", lambda: 0)
        for args in [["install", "--no-service"], ["start"]]:
            result = CliRunner().invoke(operator_app, args)
            assert result.exit_code == 1
            assert "root" in result.output


def test_uninstall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from calkit import hub

    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    # Selecting a hub sets these, which the test puts back afterward
    monkeypatch.setenv("CALKIT_HUB", "https://calkit.io")
    monkeypatch.setattr(operator, "_hub_url", "https://calkit.io")
    monkeypatch.setattr(operator, "uninstall_service", lambda key=None: None)
    calls = []

    def request(kind: str, path: str, **kwargs: Any) -> None:
        calls.append((kind, path, kwargs))
        if fail:
            response = SimpleNamespace(status_code=401)
            raise HTTPError("401: Invalid token", response=response)

    monkeypatch.setattr(hub, "_request", request)
    # With the Operator's own token, so it works however the user signed in
    # here, and one already revoked counts as done
    for fail in [False, True]:
        operator.save_config(
            {
                "name": "box",
                "hub_url": "https://calkit.io",
                "token": "cko_x",
                "api_url": "https://api.hub",
            }
        )
        result = CliRunner().invoke(operator_app, ["uninstall"])
        assert result.exit_code == 0, result.output
        assert "Could not revoke" not in result.output
        assert not os.path.exists(operator.get_config_path())
        kind, path, kwargs = calls.pop()
        assert (kind, path) == ("delete", "/operators/self")
        assert kwargs["headers"] == {"Authorization": "Bearer cko_x"}
        assert kwargs["base_url"] == "https://api.hub"


def test_stop_and_restart_every_hub(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    # Selecting a hub sets these, which the test puts back afterward
    monkeypatch.setenv("CALKIT_HUB", "https://calkit.io")
    monkeypatch.setattr(operator, "_hub_url", None)
    for url in ["https://calkit.io", "http://localhost"]:
        operator.select_hub(url)
        operator.save_config({"name": "box", "hub_url": url})
    restarted: list[str] = []

    def restart_service():
        if operator.get_hub_url() == "http://localhost" and fail:
            raise RuntimeError("Boom")
        restarted.append(operator.get_hub_url())

    monkeypatch.setattr(operator, "restart_service", restart_service)
    stopped: list[str] = []
    monkeypatch.setattr(
        operator,
        "set_service_running",
        lambda running: stopped.append(operator.get_hub_url()),
    )
    # Without --hub, every hub's Operator, each named
    fail = False
    result = CliRunner().invoke(operator_app, ["restart"])
    assert result.exit_code == 0, result.output
    assert sorted(restarted) == ["http://localhost", "https://calkit.io"]
    assert "Restarted the Operator for http://localhost" in result.output
    result = CliRunner().invoke(operator_app, ["stop"])
    assert result.exit_code == 0
    assert sorted(stopped) == ["http://localhost", "https://calkit.io"]
    # With it, only that one
    restarted.clear()
    result = CliRunner().invoke(
        operator_app, ["restart", "--hub", "https://calkit.io"]
    )
    assert restarted == ["https://calkit.io"]
    assert result.output.strip() == "Restarted the Operator"
    # One failing doesn't stop the others, but the command fails
    restarted.clear()
    fail = True
    result = CliRunner().invoke(operator_app, ["restart"])
    assert result.exit_code == 1
    assert restarted == ["https://calkit.io"]
    assert "Boom" in result.output
