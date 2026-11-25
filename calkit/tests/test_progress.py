"""Tests for ``calkit.progress``."""

import subprocess
import sys

import pytest
import typer

import calkit.progress


@pytest.fixture
def terminal(monkeypatch):
    """Make the spinner think stderr is a terminal."""
    monkeypatch.setattr("calkit.core.is_mintty", lambda f: True)


def _noisy() -> None:
    print("python says hi")
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; print('tool says hi'); "
            "print('tool warns', file=sys.stderr)",
        ],
        check=True,
    )


def test_spinner_hides_output(terminal, capfd):
    seen = []
    with calkit.progress.spinner("Checking environment 'main'", label="main"):
        assert calkit.progress.active()
        assert calkit.progress.label("spec") == "main"
        _noisy()
        calkit.progress.report("Creating environment 'main'")
        seen.append(True)
    assert seen
    assert not calkit.progress.active()
    out, err = capfd.readouterr()
    for text in ("python says hi", "tool says hi", "tool warns", "--verbose"):
        assert text not in out + err


def test_spinner_shows_tail_on_failure(terminal, capfd):
    with pytest.raises(typer.Exit):
        with calkit.progress.spinner("Checking environment 'main'"):
            _noisy()
            for i in range(30):
                print(f"line {i}")
            print("Error: it broke", file=sys.stderr)
            raise typer.Exit(1)
    _, err = capfd.readouterr()
    # Only the end
    assert "line 29" in err
    assert "Error: it broke" in err
    assert "python says hi" not in err
    assert "Rerun with --verbose for all of the output" in err


def test_spinner_clean_exit_shows_nothing(terminal, capfd):
    with pytest.raises(typer.Exit):
        with calkit.progress.spinner("Checking"):
            print("quiet")
            raise typer.Exit(0)
    out, err = capfd.readouterr()
    assert "quiet" not in out + err
    assert "--verbose" not in err


def test_spinner_off(terminal, capfd):
    # With --verbose, or inside another spinner, e.g., calkit run's,
    # nothing is hidden
    with calkit.progress.spinner("Checking", show=False):
        _noisy()
    out, err = capfd.readouterr()
    assert "python says hi" in out
    assert "tool says hi" in out
    assert "tool warns" in err
    reported = []
    with calkit.progress.reporting(reported.append):
        with calkit.progress.spinner("Checking"):
            calkit.progress.report("inner")
            _noisy()
    out, _ = capfd.readouterr()
    assert "tool says hi" in out
    assert reported == ["inner"]


def test_spinner_not_a_terminal(capfd):
    with calkit.progress.spinner("Checking"):
        assert not calkit.progress.active()
        _noisy()
    out, _ = capfd.readouterr()
    assert "tool says hi" in out
