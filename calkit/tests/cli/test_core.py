"""Tests for ``calkit.cli.core``."""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner
from typing_extensions import Annotated

from calkit.cli.core import OptionalValueCommand


def test_optional_value_command():
    class _Cmd(OptionalValueCommand):
        optional_value_options = {"--hub": "default", "--cloud": "default"}

    app = typer.Typer()

    @app.command(cls=_Cmd)
    def main(
        hub: Annotated[str | None, typer.Option("--hub", "--cloud")] = None,
        verbose: Annotated[bool, typer.Option("--verbose")] = False,
        args: Annotated[list[str] | None, typer.Argument()] = None,
    ):
        print(f"hub={hub}")

    runner = CliRunner()
    # Absent → None
    result = runner.invoke(app, [])
    assert "hub=None" in result.output
    # Bare, at end of args → assumed value
    result = runner.invoke(app, ["--hub"])
    assert "hub=default" in result.output
    # Bare, followed by another option → assumed value, option intact
    result = runner.invoke(app, ["--hub", "--verbose"])
    assert "hub=default" in result.output
    # With a value → the value
    result = runner.invoke(app, ["--hub", "https://x.io"])
    assert "hub=https://x.io" in result.output
    result = runner.invoke(app, ["--hub=https://y.io"])
    assert "hub=https://y.io" in result.output
    # The deprecated alias behaves identically
    result = runner.invoke(app, ["--cloud"])
    assert "hub=default" in result.output
    # Tokens after -- are not rewritten (they're arguments, not options)
    result = runner.invoke(app, ["--", "--hub"])
    assert "hub=None" in result.output


def test_warn(capsys) -> None:
    import io

    import pytest
    from rich.console import Console

    from calkit.cli.core import raise_error, warn

    warn("plain")
    assert capsys.readouterr().out == "Warning: plain\n"
    # Under a spinner, a warning or error goes above it rather than straight
    # to the terminal, where it would share the spinner's line
    out = io.StringIO()
    with Console(file=out, force_terminal=True).status("Working"):
        warn("careful")
        with pytest.raises(typer.Exit):
            raise_error("broken")
    assert capsys.readouterr() == ("", "")
    assert "Warning: careful" in out.getvalue()
    assert "Error: broken" in out.getvalue()


def test_warn_app_control(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import calkit.windows
    from calkit.cli.core import warn_app_control

    blocked = "An Application Control policy has blocked this file."
    # A block shown in output or an exit code is explained, whatever the
    # registry says, since other App Control policies block too
    monkeypatch.setattr(calkit.windows, "smart_app_control_on", lambda: False)
    warn_app_control(output=blocked)
    warn_app_control(returncode=0xC0E90002)
    warn_app_control(output=blocked, maybe=True)
    out, err = capsys.readouterr()
    assert out == ""
    assert err.count("Windows blocked a file from running") == 3
    assert err.count(calkit.windows.SMART_APP_CONTROL_DOCS_URL) == 3
    # Nothing to say about an ordinary failure, or a possible one with Smart
    # App Control off
    warn_app_control(output="Traceback", returncode=1)
    warn_app_control(maybe=True)
    assert capsys.readouterr() == ("", "")
    # A failure whose output went to the terminal may be a block when Smart
    # App Control is on, but one known not to be isn't
    monkeypatch.setattr(calkit.windows, "smart_app_control_on", lambda: True)
    warn_app_control(maybe=True)
    warn_app_control(returncode=1)
    out, err = capsys.readouterr()
    assert err.count("Smart App Control is on") == 1
    assert "Windows blocked" not in err
