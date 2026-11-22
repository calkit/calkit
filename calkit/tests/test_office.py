"""Tests for ``calkit.office``."""

import os
from pathlib import Path
from unittest import mock

import pytest

import calkit.office


def test_find_app_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # USERPROFILE is home on Windows
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    in_home = os.path.expanduser("~/Applications/Microsoft Word.app")
    machine_wide = "/Applications/Microsoft Word.app"
    # On macOS, the bundle in /Applications, else in ~/Applications
    for present, expected in [
        (set(), None),
        ({in_home}, in_home),
        ({in_home, machine_wide}, machine_wide),
    ]:
        with (
            mock.patch("calkit.office.sys.platform", "darwin"),
            mock.patch("calkit.office.os.path.isdir", present.__contains__),
        ):
            assert calkit.office.find_app_path("word") == expected
            assert calkit.office.app_installed("word") is (
                expected is not None
            )
    # Office doesn't run on Linux
    with mock.patch("calkit.office.sys.platform", "linux"):
        assert calkit.office.find_app_path("powerpoint") is None
