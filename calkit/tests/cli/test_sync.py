"""Tests for the sync CLI commands."""

from unittest.mock import patch

from typer.testing import CliRunner

from calkit.cli.main import app

runner = CliRunner()


def test_sync_help():
    result = runner.invoke(app, ["sync", "--help"])
    assert result.exit_code == 0
    assert "Sync with disparate systems" in result.output
    assert "git" in result.output
    assert "dvc" in result.output
    assert "overleaf" in result.output
    assert "all" in result.output


def test_sync_git_calls_pull_and_push():
    with patch("calkit.cli.main.core.pull") as mock_pull:
        with patch("calkit.cli.main.core.push") as mock_push:
            result = runner.invoke(app, ["sync", "git"])
            assert result.exit_code == 0
            mock_pull.assert_called_once_with(no_dvc=True, no_check_auth=False)
            mock_push.assert_called_once_with(no_dvc=True, no_check_auth=False)


def test_sync_dvc_calls_pull_and_push():
    with patch("calkit.cli.main.core.pull") as mock_pull:
        with patch("calkit.cli.main.core.push") as mock_push:
            result = runner.invoke(app, ["sync", "dvc"])
            assert result.exit_code == 0
            mock_pull.assert_called_once_with(no_git=True, no_check_auth=False)
            mock_push.assert_called_once_with(no_git=True, no_check_auth=False)


def test_sync_all_calls_configured_targets():
    def mock_sync_git():
        print("Mock syncing git")

    def mock_sync_dvc():
        print("Mock syncing dvc")

    def mock_sync_overleaf():
        print("Mock syncing overleaf")

    with patch.dict(
        "calkit.cli.sync.SYNC_TARGETS",
        {
            "git": {
                "sync_func": mock_sync_git,
                "is_configured_func": lambda: True,
            },
            "dvc": {
                "sync_func": mock_sync_dvc,
                "is_configured_func": lambda: False,  # Should be skipped
            },
            "overleaf": {
                "sync_func": mock_sync_overleaf,
                "is_configured_func": lambda: True,
            },
        },
        clear=True,
    ):
        result = runner.invoke(app, ["sync", "all"])
        assert result.exit_code == 0
        assert "Syncing git..." in result.output
        assert "Mock syncing git" in result.output
        assert "Skipping dvc: not configured." in result.output
        assert "Mock syncing dvc" not in result.output
        assert "Syncing overleaf..." in result.output
        assert "Mock syncing overleaf" in result.output


def test_sync_overleaf_is_accessible():
    # Since we can't easily mock the entire overleaf sync environment here
    # without duplicating test_overleaf.py, we just test that the command
    # is registered and displays its help correctly.
    result = runner.invoke(app, ["sync", "overleaf", "--help"])
    assert result.exit_code == 0
    assert "Sync folders with Overleaf" in result.output
