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
