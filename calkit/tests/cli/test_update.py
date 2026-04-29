"""Tests for ``cli.update``."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from calkit.cli.update import update_app

runner = CliRunner()
_MOCK_CONTENT = "# Calkit agent guide\n\nTest content.\n"
_BLOCK_START = "<!-- CALKIT-CONVENTIONS:START -->"
_BLOCK_END = "<!-- CALKIT-CONVENTIONS:END -->"


def test_update_environment(tmp_dir):
    # Test we can update an environment
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "julia-env", "-n", "main", "--julia", "1.11"]
    )
    subprocess.check_call(
        [
            "calkit",
            "update",
            "env",
            "-n",
            "main",
            "--add",
            "IJulia",
        ]
    )


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "calkit.cli.update.os.path.expanduser",
        lambda p: str(tmp_path) if p == "~" else p,
    )
    return tmp_path


def _mock_get():
    resp = MagicMock()
    resp.text = _MOCK_CONTENT
    return resp


def test_update_agent_instructions_codex(fake_home):
    agents_md = fake_home / "AGENTS.md"
    # Explicit --tool codex always writes, even if file didn't exist.
    with patch("calkit.cli.update.requests.get", return_value=_mock_get()):
        result = runner.invoke(
            update_app, ["agent-instructions", "--tool", "codex"]
        )
    assert result.exit_code == 0
    assert agents_md.exists()
    content = agents_md.read_text()
    assert _BLOCK_START in content
    assert _BLOCK_END in content
    assert _MOCK_CONTENT.strip() in content
    # User adds their own content above the block.
    agents_md.write_text("# My project\n\n" + agents_md.read_text())
    with patch("calkit.cli.update.requests.get", return_value=_mock_get()):
        runner.invoke(update_app, ["agent-instructions", "--tool", "codex"])
    content = agents_md.read_text()
    # User content preserved, block not duplicated.
    assert "# My project" in content
    assert content.count(_BLOCK_START) == 1


def test_update_agent_instructions_cursor(fake_home):
    cursor_rules = fake_home / ".cursor" / "rules"
    mdc = cursor_rules / "calkit.mdc"
    # Explicit --tool cursor creates dirs and file even if ~/.cursor didn't
    # exist.
    with patch("calkit.cli.update.requests.get", return_value=_mock_get()):
        result = runner.invoke(
            update_app, ["agent-instructions", "--tool", "cursor"]
        )
    assert result.exit_code == 0
    assert mdc.exists()
    content = mdc.read_text()
    assert "alwaysApply: true" in content
    assert _BLOCK_START in content
    assert _MOCK_CONTENT.strip() in content


def test_update_agent_instructions_all_skips_unconfigured(fake_home):
    # Only copilot is configured (~/.github exists); others absent.
    github_dir = fake_home / ".github"
    github_dir.mkdir()
    with patch("calkit.cli.update.requests.get", return_value=_mock_get()):
        result = runner.invoke(update_app, ["agent-instructions"])
    assert result.exit_code == 0
    copilot_file = github_dir / "copilot-instructions.md"
    assert copilot_file.exists()
    assert _BLOCK_START in copilot_file.read_text()
    # No other tool dirs should be created.
    assert not (fake_home / ".cursor").exists()
    assert not (fake_home / ".gemini").exists()
    assert not (fake_home / "AGENTS.md").exists()


def test_update_agent_instructions_all_nothing_configured(fake_home):
    with patch(
        "calkit.cli.update.requests.get", return_value=_mock_get()
    ) as mock_get:
        result = runner.invoke(update_app, ["agent-instructions"])
    assert result.exit_code == 0
    mock_get.assert_not_called()
    assert not any(fake_home.iterdir())
