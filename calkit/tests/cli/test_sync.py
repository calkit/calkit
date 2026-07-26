"""Tests for the sync CLI commands."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from calkit.cli.main import app

runner = CliRunner()


def test_sync_help():
    result = runner.invoke(app, ["sync", "--help"])
    assert result.exit_code == 0
    assert "Sync with external systems" in result.output
    assert "git" in result.output
    assert "dvc" in result.output
    assert "overleaf" in result.output
    assert "all" in result.output


def test_sync_git_calls_pull_and_push():
    mock_repo = MagicMock()
    mock_repo.remotes = ["origin"]
    with patch("calkit.git.get_repo", return_value=mock_repo):
        with patch("calkit.cli.main.core.pull") as mock_pull:
            with patch("calkit.cli.main.core.push") as mock_push:
                result = runner.invoke(app, ["sync", "git"])
                assert result.exit_code == 0
                mock_pull.assert_called_once_with(
                    no_dvc=True, no_check_auth=False
                )
                mock_push.assert_called_once_with(
                    no_dvc=True, no_check_auth=False
                )


def test_sync_git_errors_when_not_initialized():
    with patch("calkit.git.get_repo", side_effect=Exception("not a repo")):
        result = runner.invoke(app, ["sync", "git"])
        assert result.exit_code != 0
        assert "No Git repository found" in result.output


def test_sync_dvc_calls_pull_and_push():
    with patch("calkit.dvc.get_dvc_repo"):
        with patch("calkit.dvc.get_remotes", return_value={"origin": "url"}):
            with patch("calkit.cli.main.core.pull") as mock_pull:
                with patch("calkit.cli.main.core.push") as mock_push:
                    result = runner.invoke(app, ["sync", "dvc"])
                    assert result.exit_code == 0
                    mock_pull.assert_called_once_with(
                        no_git=True, no_check_auth=False
                    )
                    mock_push.assert_called_once_with(
                        no_git=True, no_check_auth=False
                    )


def test_sync_dvc_errors_when_not_initialized():
    with patch(
        "calkit.dvc.get_dvc_repo", side_effect=Exception("not a dvc repo")
    ):
        result = runner.invoke(app, ["sync", "dvc"])
        assert result.exit_code != 0
        assert "No DVC repository found" in result.output


def test_sync_all_runs_all_targets():
    def mock_sync_git():
        print("Mock syncing git")

    def mock_sync_dvc():
        print("Mock syncing dvc")

    def mock_sync_overleaf():
        print("Mock syncing overleaf")

    with patch("calkit.cli.sync.sync_git", mock_sync_git):
        with patch("calkit.cli.sync.sync_dvc", mock_sync_dvc):
            with patch("calkit.cli.sync.sync_overleaf", mock_sync_overleaf):
                result = runner.invoke(app, ["sync", "all"])
                assert result.exit_code == 0
                assert "Syncing git..." in result.output
                assert "Mock syncing git" in result.output
                assert "Syncing dvc..." in result.output
                assert "Mock syncing dvc" in result.output
                assert "Syncing overleaf..." in result.output
                assert "Mock syncing overleaf" in result.output


def test_sync_all_reports_target_failures():
    def mock_sync_git():
        print("Mock syncing git")

    def mock_sync_dvc():
        raise RuntimeError("dvc is broken")

    with patch("calkit.cli.sync.sync_git", mock_sync_git):
        with patch("calkit.cli.sync.sync_dvc", mock_sync_dvc):
            with patch("calkit.cli.sync.sync_overleaf"):
                result = runner.invoke(app, ["sync", "all"])
                assert result.exit_code == 1
                assert "Syncing git..." in result.output
                assert "Mock syncing git" in result.output
                assert "Syncing dvc..." in result.output
                assert "Failed to sync dvc: dvc is broken" in result.output


def test_sync_overleaf_is_accessible():
    # Since we can't easily mock the entire overleaf sync environment here
    # without duplicating test_overleaf.py, we just test that the command
    # is registered and displays its help correctly.
    result = runner.invoke(app, ["sync", "overleaf", "--help"])
    assert result.exit_code == 0
    assert "Sync folders with Overleaf" in result.output
