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
    resp.raise_for_status = MagicMock()
    return resp


def test_update_agent_instructions_codex(fake_home):
    skills_dir = fake_home / ".agents" / "skills"
    # Explicit --tool codex copies bundled skills and does not require HTTP.
    with patch("calkit.cli.update.requests.get") as mock_get:
        result = runner.invoke(
            update_app, ["agent-instructions", "--tool", "codex"]
        )
    assert result.exit_code == 0
    assert (skills_dir / "add-pipeline-stage" / "SKILL.md").exists()
    assert (skills_dir / "calkit-conventions" / "SKILL.md").exists()
    assert (skills_dir / "create-pipeline" / "SKILL.md").exists()
    mock_get.assert_not_called()
    # Existing custom files should be preserved by copytree dirs_exist_ok.
    custom_skill = skills_dir / "my-skill" / "SKILL.md"
    custom_skill.parent.mkdir(parents=True)
    custom_skill.write_text("# Custom\n")
    with patch("calkit.cli.update.requests.get") as mock_get2:
        runner.invoke(update_app, ["agent-instructions", "--tool", "codex"])
    assert custom_skill.exists()
    mock_get2.assert_not_called()


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


def test_update_agent_instructions_all_writes_all_tools(fake_home):
    # --tool all writes all supported destinations and creates directories.
    with patch("calkit.cli.update.requests.get", return_value=_mock_get()):
        result = runner.invoke(
            update_app, ["agent-instructions", "--tool", "all"]
        )
    assert result.exit_code == 0
    assert (fake_home / ".github" / "copilot-instructions.md").exists()
    assert (fake_home / ".cursor" / "rules" / "calkit.mdc").exists()
    assert (fake_home / ".gemini" / "GEMINI.md").exists()
    assert (fake_home / ".agents" / "skills" / "calkit-conventions").exists()
    assert not (fake_home / "AGENTS.md").exists()


def test_update_agent_instructions_auto_updates_detected_tools(
    fake_home,
):
    # --tool auto always updates codex and also updates tools with an
    # existing block or detected config.
    # Set up copilot with the block and cursor configured without a block.
    github_dir = fake_home / ".github"
    github_dir.mkdir()
    copilot_file = github_dir / "copilot-instructions.md"
    copilot_file.write_text(
        f"# My instructions\n\n{_BLOCK_START}\nold content\n{_BLOCK_END}\n"
    )
    (fake_home / ".cursor").mkdir()
    with patch("calkit.cli.update.requests.get", return_value=_mock_get()):
        result = runner.invoke(update_app, ["agent-instructions"])
    assert result.exit_code == 0
    assert _MOCK_CONTENT.strip() in copilot_file.read_text()
    assert (fake_home / ".cursor" / "rules" / "calkit.mdc").exists()
    assert (fake_home / ".agents" / "skills" / "calkit-conventions").exists()
    assert not (fake_home / "AGENTS.md").exists()


def test_update_agent_instructions_auto_nothing_to_update(fake_home):
    # --tool auto always updates codex skills even if no other tools detected.
    with patch(
        "calkit.cli.update.requests.get", return_value=_mock_get()
    ) as mock_get:
        result = runner.invoke(update_app, ["agent-instructions"])
    assert result.exit_code == 0
    mock_get.assert_not_called()
    assert (fake_home / ".agents" / "skills" / "calkit-conventions").exists()
    assert not (fake_home / "AGENTS.md").exists()


def test_update_agent_instructions_handles_missing_block_end(fake_home):
    agents_md = fake_home / ".github" / "copilot-instructions.md"
    agents_md.parent.mkdir(parents=True)
    agents_md.write_text(f"# Header\n\n{_BLOCK_START}\nold content\n")
    with patch("calkit.cli.update.requests.get", return_value=_mock_get()):
        result = runner.invoke(
            update_app, ["agent-instructions", "--tool", "copilot"]
        )
    assert result.exit_code == 0
    content = agents_md.read_text()
    assert content.count(_BLOCK_START) == 1
    assert content.count(_BLOCK_END) == 1
    assert _MOCK_CONTENT.strip() in content


def test_update_agent_instructions_uses_timeout(fake_home):
    with patch(
        "calkit.cli.update.requests.get", return_value=_mock_get()
    ) as mock_get:
        result = runner.invoke(
            update_app, ["agent-instructions", "--tool", "copilot"]
        )
    assert result.exit_code == 0
    assert mock_get.call_args.kwargs["timeout"] == 10


def test_update_agent_instructions_auto_warns_on_download_failure(fake_home):
    github_dir = fake_home / ".github"
    github_dir.mkdir()
    copilot_file = github_dir / "copilot-instructions.md"
    copilot_file.write_text(
        f"# My instructions\n\n{_BLOCK_START}\nold content\n{_BLOCK_END}\n"
    )
    with patch(
        "calkit.cli.update.requests.get", side_effect=RuntimeError("boom")
    ):
        result = runner.invoke(update_app, ["agent-instructions"])
    assert result.exit_code == 0
    assert "Warning: failed to refresh agent instructions" in result.stdout
