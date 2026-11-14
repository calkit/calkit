"""Tests for ``calkit.cli.browser_link``."""

import os
import platform

import pytest
from typer.testing import CliRunner

from calkit.cli.main import app

runner = CliRunner()


def test_browser_link(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Windows registers hosts in the registry")
    home = tmp_path / "home"
    monkeypatch.setenv("CALKIT_USER_HOME", str(home))
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    # With no browser run here, there's nowhere to set it up
    result = runner.invoke(app, ["browser-link", "install"])
    assert result.exit_code == 0, result.output
    assert "No supported browser" in result.output
    os.makedirs(home / ".config" / "google-chrome")
    result = runner.invoke(
        app, ["browser-link", "install", "--extension-id", "abc"]
    )
    assert result.exit_code == 0, result.output
    assert "from chrome" in result.output
    result = runner.invoke(app, ["browser-link", "status"])
    assert result.exit_code == 0, result.output
    assert "chrome: allows the Calkit extension, abc" in result.output
    assert "answers when the browser starts it" in result.output
    result = runner.invoke(app, ["browser-link", "uninstall"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["browser-link", "status"])
    assert result.exit_code != 0
    assert "chrome: not set up" in result.output
    assert "calkit browser-link install" in result.output
