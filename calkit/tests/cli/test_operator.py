"""Tests for ``calkit.cli.operator``."""

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
