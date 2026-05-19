"""Tests for the ``install`` module."""

from __future__ import annotations

import os
import subprocess
from unittest import mock

import pytest

import calkit
from calkit import install


@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_installer_registry_includes_aliases():
    # rustup/cargo and juliaup/julia share their installer entries by
    # reference, so editing one updates the other -- guard against any
    # future refactor that accidentally splits them.
    assert install.INSTALLERS["cargo"] is install.INSTALLERS["rustup"]
    assert install.INSTALLERS["julia"] is install.INSTALLERS["juliaup"]
    for name in ("rustup", "juliaup", "cargo", "julia"):
        entry = install.INSTALLERS[name]
        assert "unix" in entry and "windows" in entry
        assert entry["unix"]["script"]
        assert entry["unix"]["path_add"]


def test_get_installer():
    # Known app on a supported platform returns an entry with a script
    # and an install-location hint for PATH injection.
    with mock.patch("calkit.install.sys.platform", "linux"):
        entry = install.get_installer("pixi")
    assert entry is not None
    assert "script" in entry and "path_add" in entry
    # Unknown apps return None so callers can fall through cleanly.
    assert install.get_installer("definitely-not-a-real-tool") is None
    # Windows resolves to the powershell variant.
    with mock.patch("calkit.install.sys.platform", "win32"):
        win_entry = install.get_installer("uv")
    assert win_entry is not None
    assert "powershell" in win_entry["script"].lower()


def test_install_and_path_injection(tmp_dir, monkeypatch):
    # Simulate a successful installer that drops a binary into a known
    # directory; ``install()`` should prepend that directory to PATH and
    # return True once ``shutil.which`` can see the binary.
    fake_bin_dir = tmp_dir / "fakebin"
    fake_bin_dir.mkdir()
    fake_binary = fake_bin_dir / "pixi"
    fake_binary.write_text("#!/bin/sh\nexit 0\n")
    fake_binary.chmod(0o755)
    fake_entry: install.Installer = {
        "script": "true",
        "path_add": str(fake_bin_dir),
    }
    monkeypatch.setattr("calkit.install.get_installer", lambda app: fake_entry)
    # Start without the fake dir on PATH and confirm we can't see it.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    import shutil

    assert shutil.which("pixi") is None
    assert install.install("pixi") is True
    assert str(fake_bin_dir) in os.environ["PATH"].split(os.pathsep)
    assert shutil.which("pixi") is not None
    # An installer that exits non-zero returns False without touching PATH.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    with mock.patch(
        "calkit.install.subprocess.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=1),
    ):
        assert install.install("pixi") is False
    assert str(fake_bin_dir) not in os.environ["PATH"].split(os.pathsep)


def test_prompt_and_install(monkeypatch):
    fake_entry: install.Installer = {"script": "echo ok", "path_add": "/tmp"}
    monkeypatch.setattr("calkit.install.get_installer", lambda app: fake_entry)
    # Non-interactive: never runs install, just prints the fix-it.
    with mock.patch("calkit.install.install") as m_install:
        assert install.prompt_and_install("pixi", interactive=False) is False
        m_install.assert_not_called()
    # Interactive "n" declines without running.
    with (
        mock.patch("builtins.input", return_value="n"),
        mock.patch("calkit.install.install") as m_install,
    ):
        assert install.prompt_and_install("pixi", interactive=True) is False
        m_install.assert_not_called()
    # Interactive "y" runs install and surfaces its result.
    with (
        mock.patch("builtins.input", return_value="y"),
        mock.patch("calkit.install.install", return_value=True),
    ):
        assert install.prompt_and_install("pixi", interactive=True) is True
    # Unknown app -> no installer -> False.
    monkeypatch.setattr("calkit.install.get_installer", lambda app: None)
    assert install.prompt_and_install("nope", interactive=True) is False


def test_check_system_deps_orders_and_auto_installs(tmp_dir, monkeypatch):
    # Mixed-order deps: a setup step listed first, an env-var, and an
    # app. Verify the env-var is prompted first, then the missing app is
    # auto-installed, then the setup step runs (which references the
    # just-installed app via $PATH).
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    fake_bin_dir = tmp_dir / "bin"
    fake_bin_dir.mkdir()
    fake_pixi = fake_bin_dir / "pixi"
    fake_pixi.write_text("#!/bin/sh\nexit 0\n")
    fake_pixi.chmod(0o755)
    fake_entry: install.Installer = {
        "script": "true",
        "path_add": str(fake_bin_dir),
    }
    monkeypatch.setattr(
        "calkit.install.get_installer",
        lambda app: fake_entry if app == "pixi" else None,
    )
    ck_info = {
        "dependencies": [
            {
                "name": "auth-ok",
                "kind": "setup",
                "check_command": "pixi --version",
            },
            {"name": "API_KEY", "kind": "env-var", "default": "secret"},
            "pixi",
        ]
    }
    with mock.patch("builtins.input", side_effect=["", "y"]):
        calkit.check_system_deps(ck_info=ck_info, interactive=True)
    # Env-var was prompted (empty -> default), exported, persisted.
    assert os.environ["API_KEY"] == "secret"
    # Auto-install ran and put pixi on PATH for the in-process setup check.
    assert str(fake_bin_dir) in os.environ["PATH"].split(os.pathsep)
