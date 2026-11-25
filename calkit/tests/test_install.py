"""Tests for the ``install`` module."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

import calkit
from calkit import install

# These tests fabricate a unix-shebang shell script as a fake installed binary
# and rely on shutil.which finding it without a Windows extension; that does
# not translate to Windows, where PATHEXT lookup needs .exe/.bat/.cmd. The
# behavior under test is platform-independent — only the test fixtures need a
# Windows port.
skipif_windows_fake_binary = pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: port fake-binary fixture to Windows (needs .bat/.cmd)",
)


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
    # gh comes from each platform's package manager, or pixi on Linux
    for platform, expected in [
        ("darwin", "brew"),
        ("linux", "pixi"),
        ("win32", "winget"),
    ]:
        with mock.patch("calkit.install.sys.platform", platform):
            gh = install.get_installer("gh")
        assert gh is not None and gh["script"].startswith(expected)
    # make only needs installing on Windows
    with mock.patch("calkit.install.sys.platform", "win32"):
        make = install.get_installer("make")
    assert make is not None and "ezwinports.make" in make["script"]
    with mock.patch("calkit.install.sys.platform", "linux"):
        assert install.get_installer("make") is None
    # Office apps come one at a time on macOS but together on Windows, and
    # point Linux at LibreOffice
    for app, cask, exe in [
        ("word", "microsoft-word", "Winword.exe"),
        ("excel", "microsoft-excel", "excel.exe"),
        ("powerpoint", "microsoft-powerpoint", "powerpnt.exe"),
    ]:
        with mock.patch("calkit.install.sys.platform", "darwin"):
            mac = install.get_installer(app)
        assert mac is not None and mac["script"].endswith(cask)
        # Homebrew can put it in ~/Applications
        assert any(p.startswith("~/Applications") for p in mac["path_add"])
        with mock.patch("calkit.install.sys.platform", "win32"):
            win = install.get_installer(app)
        assert win is not None and "Microsoft.Office" in win["script"]
        assert win["binary"] == exe
        with mock.patch("calkit.install.sys.platform", "linux"):
            assert install.get_installer(app) is None
            message = install.get_unsupported_message(app)
        assert message is not None and "libreoffice" in message


@skipif_windows_fake_binary
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
    # Where it's installed but not on PATH, it's still found, without
    # changing PATH
    assert install.find("pixi") == shutil.which("pixi", path=str(fake_bin_dir))
    assert os.environ["PATH"] == "/usr/bin:/bin"
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
    # Under WSL, Docker Desktop on Windows is offered as the alternative to
    # installing Docker Engine, but nowhere else, e.g., when testing on Windows
    monkeypatch.setattr("calkit.install._current_platform", lambda: "linux")
    for wsl in [True, False]:
        monkeypatch.setattr("calkit.core.is_wsl", lambda: wsl)
        with (
            mock.patch("builtins.input", return_value="n"),
            mock.patch("builtins.print") as m_print,
        ):
            install.prompt_and_install("docker", interactive=True)
        printed = " ".join(str(c.args[0]) for c in m_print.call_args_list)
        assert ("WSL integration" in printed) is wsl
    # Unknown app -> no installer -> False.
    monkeypatch.setattr("calkit.install.get_installer", lambda app: None)
    assert install.prompt_and_install("nope", interactive=True) is False


def test_docker_windows_requirements(monkeypatch: pytest.MonkeyPatch) -> None:
    def run_wsl(stdout: bytes, returncode: int = 0) -> None:
        monkeypatch.setattr(
            "calkit.install.subprocess.run",
            lambda *a, **k: subprocess.CompletedProcess(
                a, returncode, stdout=stdout
            ),
        )

    # WSL's version is read whether it writes UTF-8 or UTF-16, and the
    # inbox version, or none, has no version
    for stdout, returncode, version in [
        (
            "WSL version: 2.6.1.0\nKernel version: 6.6.87.2-1\n".encode(),
            0,
            (2, 6, 1),
        ),
        ("WSL-Version: 2.0.14.0\r\n".encode("utf-16-le"), 0, (2, 0, 14)),
        (b"Usage: wsl.exe [Argument]", 1, None),
    ]:
        run_wsl(stdout, returncode)
        assert install.get_wsl_version() == version
    monkeypatch.setattr(
        "calkit.install.subprocess.run", mock.Mock(side_effect=OSError)
    )
    assert install.get_wsl_version() is None
    # Docker Desktop says what to update, Windows first
    for build, wsl_version, expected in [
        ("10.0.19044", (2, 6, 1), "build 19044"),
        ("10.0.22621", (2, 6, 1), "Windows 11 23H2"),
        ("10.0.19045", None, "inbox version"),
        ("10.0.26100", (2, 0, 14), "is 2.0.14"),
        ("10.0.26100", (2, 1, 5), None),
    ]:
        with (
            mock.patch("platform.version", return_value=build),
            mock.patch(
                "calkit.install.get_wsl_version", return_value=wsl_version
            ),
        ):
            message = install.get_docker_windows_message()
        if expected is None:
            assert message is None
        else:
            assert message is not None and expected in message
    # It's shown before asking to install Docker on Windows, or before
    # installing it with --yes
    from typer.testing import CliRunner

    from calkit.cli.main.core import app as calkit_app

    with (
        mock.patch("calkit.install.sys.platform", "win32"),
        mock.patch(
            "calkit.install.get_docker_windows_message", return_value="Old"
        ),
    ):
        script = install.INSTALLERS["docker"]["windows"]["script"]
        with (
            mock.patch("builtins.input", return_value="n"),
            mock.patch("builtins.print") as m_print,
        ):
            install.prompt_and_install("docker", interactive=True)
        printed = [str(c.args[0]) for c in m_print.call_args_list]
        assert printed[:2] == ["  Old", f"  {script}"]
        with mock.patch("calkit.install.install", return_value=True):
            result = CliRunner().invoke(
                calkit_app, ["install", "docker", "--yes"]
            )
        assert "Warning: Old" in result.output


@skipif_windows_fake_binary
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


def test_nix_installer_registered_only_on_unix():
    # Nix has no native Windows installer; we expect get_installer to
    # return None there and ``get_unsupported_message`` to surface the
    # WSL2 hint so callers can give a useful error.
    with mock.patch("calkit.install.sys.platform", "linux"):
        entry = install.get_installer("nix")
        assert entry is not None
        assert "determinate.systems" in entry["script"]
        assert entry["path_add"] == "/nix/var/nix/profiles/default/bin"
        assert install.get_unsupported_message("nix") is None
    with mock.patch("calkit.install.sys.platform", "win32"):
        assert install.get_installer("nix") is None
        msg = install.get_unsupported_message("nix")
        assert msg is not None
        assert "WSL2" in msg
    # Apps without an explicit unsupported entry just return None.
    assert install.get_unsupported_message("pixi") is None


def test_install_nix_on_windows_surfaces_wsl2_message(monkeypatch):
    # ``calkit install nix`` on Windows must give the WSL2 message rather
    # than the generic "no registered installer" error.
    from typer.testing import CliRunner

    from calkit.cli.main.core import app as calkit_app

    runner = CliRunner()
    with mock.patch("calkit.install.sys.platform", "win32"):
        result = runner.invoke(calkit_app, ["install", "nix"])
    assert result.exit_code != 0
    assert "WSL2" in (result.output + (result.stderr or ""))


def test_install_cli_command(monkeypatch):
    # The ``calkit install <name>`` subcommand wires three paths:
    # unknown app -> error, --yes -> direct ``install`` (no prompt),
    # default -> ``prompt_and_install``.
    from typer.testing import CliRunner

    from calkit.cli.main.core import app as calkit_app

    runner = CliRunner()
    # Unknown app surfaces the known list and exits non-zero.
    result = runner.invoke(calkit_app, ["install", "definitely-not-a-tool"])
    assert result.exit_code != 0
    assert "No registered installer" in (result.output + (result.stderr or ""))
    # ``--yes`` skips the prompt and goes straight through ``install``;
    # ``prompt_and_install`` must not be called.
    with (
        mock.patch("calkit.install.install", return_value=True) as m_install,
        mock.patch("calkit.install.prompt_and_install") as m_prompt,
    ):
        result = runner.invoke(calkit_app, ["install", "pixi", "--yes"])
        assert result.exit_code == 0
        m_install.assert_called_once_with("pixi")
        m_prompt.assert_not_called()
    # Apps are installed by the binary they provide, e.g., node for nodejs
    for alias, app in [("nodejs", "node"), ("vscode", "code")]:
        with (
            mock.patch("calkit.install.sys.platform", "win32"),
            mock.patch(
                "calkit.install.install", return_value=True
            ) as m_install,
        ):
            result = runner.invoke(calkit_app, ["install", alias, "--yes"])
            assert result.exit_code == 0, result.output
            m_install.assert_called_once_with(app)
    # Default path delegates to ``prompt_and_install``; a False return
    # value surfaces as a non-zero exit.
    with mock.patch(
        "calkit.install.prompt_and_install", return_value=False
    ) as m_prompt:
        result = runner.invoke(calkit_app, ["install", "pixi"])
        assert result.exit_code != 0
        m_prompt.assert_called_once()
        assert m_prompt.call_args.args[0] == "pixi"
    # An agent that's installed only gets Calkit's plugin, and one that
    # isn't is installed first
    for found in [True, False]:
        finds = ["/bin/claude"] * 2 if found else [None, "/bin/claude"]
        with (
            mock.patch("calkit.install.find", side_effect=finds),
            mock.patch("calkit.install.can_run_git", return_value=True),
            mock.patch(
                "calkit.install.install", return_value=True
            ) as m_install,
            mock.patch("calkit.install.subprocess.call", return_value=0) as m,
        ):
            result = runner.invoke(calkit_app, ["install", "claude", "-y"])
            assert result.exit_code == 0, result.output
            assert m_install.called is not found
            assert [c.args[0] for c in m.call_args_list] == [
                [
                    "/bin/claude",
                    "plugin",
                    "marketplace",
                    "add",
                    "calkit/calkit",
                ],
                ["/bin/claude", "plugin", "install", "calkit@calkit"],
            ]
            assert "Added Calkit plugin" in result.output
    # Where Git doesn't run, e.g., macOS without the Command Line Tools,
    # it's installed before adding the plugin, and only the last plugin
    # command has to succeed
    with (
        mock.patch("calkit.install.find", return_value="/bin/codex"),
        mock.patch("calkit.install.can_run_git", return_value=False),
        mock.patch("calkit.install.install", return_value=True) as m_install,
        mock.patch(
            "calkit.install.subprocess.call", side_effect=[1, 0]
        ) as m_call,
    ):
        result = runner.invoke(calkit_app, ["install", "codex", "-y"])
        assert result.exit_code == 0, result.output
        m_install.assert_called_once_with("git")
        assert m_call.call_args.args[0] == [
            "/bin/codex",
            "plugin",
            "add",
            "calkit@calkit",
        ]
    # Claude Code adds plugins only once logged in, which it says as JSON,
    # and an agent that can't say counts as logged in
    for agent, stdout, expected in [
        ("claude", '{"loggedIn": false}', False),
        ("claude", '{"loggedIn": true}', True),
        ("claude", "error: unknown command 'auth'", True),
        ("codex", '{"loggedIn": false}', True),
    ]:
        with mock.patch(
            "calkit.install.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout=stdout),
        ):
            assert install.is_agent_logged_in(agent, "/bin/x") is expected
    # Not logged in, it's offered on a terminal, otherwise said what to run
    for tty in [False, True]:
        with (
            mock.patch("calkit.install.find", return_value="/bin/claude"),
            mock.patch("calkit.install.can_run_git", return_value=True),
            mock.patch(
                "calkit.install.is_agent_logged_in", return_value=False
            ),
            mock.patch("calkit.core.is_tty", return_value=tty),
            mock.patch("calkit.install.subprocess.call", return_value=0) as m,
        ):
            result = runner.invoke(calkit_app, ["install", "claude", "-y"])
        calls = [c.args[0][1:] for c in m.call_args_list]
        if tty:
            assert result.exit_code == 0, result.output
            assert calls[0] == ["auth", "login"] and len(calls) == 3
        else:
            assert result.exit_code != 0
            assert "'claude auth login'" in result.output + (
                result.stderr or ""
            )
            assert not calls
    # OpenCode has no installer on Windows, but once it's installed, it
    # still gets the plugin
    for found in [None, "C:/oc.exe"]:
        with (
            mock.patch("calkit.install.sys.platform", "win32"),
            mock.patch("calkit.install.find", return_value=found),
            mock.patch("calkit.install.can_run_git", return_value=True),
            mock.patch("calkit.install.subprocess.call", return_value=1),
        ):
            result = runner.invoke(calkit_app, ["install", "opencode", "-y"])
        output = result.output + (result.stderr or "")
        assert result.exit_code != 0
        if found is None:
            assert "npm" in output
        else:
            assert "Failed to add Calkit plugin" in output


@skipif_windows_fake_binary
def test_platform_entries_prerequisites_and_record(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # macOS gets its own entries, falls back to the shared unix ones, and
    # names Homebrew as a prerequisite for what's installed through it
    with mock.patch("calkit.install.sys.platform", "darwin"):
        brew = install.get_installer("brew")
        assert brew is not None and "Homebrew" in brew["script"]
        assert install.get_installer("pixi") is not None
        # Except Git, which comes with Apple's Command Line Tools
        git = install.get_installer("git")
        assert git is not None and "xcode-select --install" in git["script"]
        assert "requires" not in git
        # VS Code goes in the user's own Applications without access to
        # /Applications, e.g., on a managed Mac
        code = install.get_installer("code")
        assert code is not None and '"$HOME/Applications"' in code["script"]
        assert install.get_installer("choco") is None
        assert "Windows-only" in str(install.get_unsupported_message("choco"))
        # Colima comes with the Docker CLI it's no use without, unless
        # there's one already, e.g., from Docker Desktop
        colima = install.get_installer("colima")
        assert colima is not None and colima.get("requires") == ["brew"]
        assert colima["script"] == (
            "brew install colima && "
            "{ command -v docker >/dev/null || brew install docker; }"
        )
    # Linux has no single package manager, so Git says what to run
    with mock.patch("calkit.install.sys.platform", "linux"):
        assert install.get_installer("git") is None
        assert "package manager" in str(install.get_unsupported_message("git"))
        assert install.get_installer("docker") is not None
        assert install.get_installer("brew") is None
        # Docker runs natively there, so Colima points to Docker Engine
        assert install.get_installer("colima") is None
        assert "Docker runs natively" in str(
            install.get_unsupported_message("colima")
        )
    with mock.patch("calkit.install.sys.platform", "win32"):
        choco = install.get_installer("choco")
        assert choco is not None and "chocolatey" in choco["script"]
        assert install.get_installer("brew") is None
        r = install.get_installer("R")
        assert r is not None and "*" in str(r["path_add"])
        assert install.get_installer("colima") is None
        assert "Docker Desktop" in str(
            install.get_unsupported_message("colima")
        )
        # Docker Desktop gets Virtual Machine Platform enabled first, but
        # only where it isn't
        docker = install.get_installer("docker")
        assert docker is not None
        check, _, rest = docker["script"].partition(" -ne 1) { ")
        assert check.endswith("'VirtualMachinePlatform').InstallState")
        enable, _, winget = rest.partition('}" && ')
        assert "-Verb runAs" in enable and "-NoRestart" in enable
        assert winget == install._WINGET + "Docker.DockerDesktop"
        # Claude Code needs Git Bash, and OpenCode comes from npm
        claude = install.get_installer("claude")
        assert claude is not None and claude.get("requires") == ["git"]
        assert install.get_installer("codex") is not None
        assert install.get_installer("opencode") is None
        assert "npm" in str(install.get_unsupported_message("opencode"))
    # Aliases share entries by reference
    assert install.INSTALLERS["mamba"] is install.INSTALLERS["conda"]
    assert install.INSTALLERS["Rscript"] is install.INSTALLERS["R"]
    assert install.INSTALLERS["npm"] is install.INSTALLERS["node"]
    assert install.INSTALLERS["npx"] is install.INSTALLERS["node"]
    # Node comes through pixi everywhere
    for platform in ["darwin", "linux", "win32"]:
        with mock.patch("calkit.install.sys.platform", platform):
            node = install.get_installer("node")
            assert node is not None and node.get("requires") == ["pixi"]
    # Without pixi, Node asks about pixi first, and declining installs neither
    with (
        mock.patch("calkit.install.shutil.which", return_value=None),
        mock.patch("builtins.input", return_value="n") as m_input,
        mock.patch("calkit.install.install") as m_install,
    ):
        assert install.prompt_and_install("node", interactive=True) is False
    assert "'pixi'" in m_input.call_args.args[0]
    m_install.assert_not_called()
    # With pixi installed off PATH, e.g., since this shell started, it's put
    # on PATH rather than offered again
    with (
        mock.patch("calkit.install.shutil.which", return_value=None),
        mock.patch(
            "calkit.install.find",
            side_effect=lambda app: "/pixi" if app == "pixi" else None,
        ),
        mock.patch("calkit.install._add_to_path") as m_add,
        mock.patch("builtins.input", return_value="n") as m_input,
    ):
        assert install.prompt_and_install("node", interactive=True) is False
    assert "'node'" in m_input.call_args.args[0]
    assert m_add.call_args.args[0] == install.get_installer("pixi")
    # On Windows pixi comes from winget, since Microsoft Defender blocks its
    # own script
    with mock.patch("calkit.install.sys.platform", "win32"):
        pixi = install.get_installer("pixi")
    assert pixi is not None and "prefix-dev.pixi" in pixi["script"]
    # LibreOffice is found by its soffice command, and on Linux comes with
    # the Math component distributions package separately
    assert install.INSTALLERS["soffice"] is install.INSTALLERS["libreoffice"]
    for platform in ("darwin", "linux", "win32"):
        with mock.patch("calkit.install.sys.platform", platform):
            lo = install.get_installer("libreoffice")
            assert lo is not None and lo.get("binary") == "soffice"
            if platform == "linux":
                assert "libreoffice-math" in lo["script"]
    # A fake registry with a prerequisite: installing the tool installs the
    # prerequisite first, both land on PATH, and both are recorded
    fake_bin = tmp_dir / "bin"
    fake_bin.mkdir()
    registry: dict[str, install.Installer] = {
        "prereq": {"script": "install-prereq", "path_add": str(fake_bin)},
        "tool": {
            "script": "install-tool",
            "path_add": str(fake_bin),
            "requires": ["prereq"],
        },
    }
    monkeypatch.setattr("calkit.install.get_installer", registry.get)
    log_path = tmp_dir / "installed.json"
    monkeypatch.setattr(
        "calkit.install.get_install_log_path", lambda: str(log_path)
    )
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    ran: list[str] = []

    def fake_run(script: str, shell: bool) -> subprocess.CompletedProcess:
        ran.append(script)
        # The prerequisite and tool are there once installed
        name = script.removeprefix("install-")
        if name in ("prereq", "tool"):
            exe = fake_bin / name
            exe.write_text("#!/bin/sh\nexit 0\n")
            exe.chmod(0o755)
        return subprocess.CompletedProcess(args=[], returncode=0)

    with mock.patch("calkit.install.subprocess.run", side_effect=fake_run):
        assert install.install("tool") is True
    assert ran == ["install-prereq", "install-tool"]
    log = install.read_install_log()
    assert [rec["app"] for rec in log] == ["prereq", "tool"]
    assert log[1]["script"] == "install-tool"
    assert log[1]["installed_at"]
    # An app whose command is named otherwise is checked for by that name
    registry["suite"] = {
        "script": "install-suite",
        "path_add": str(fake_bin),
        "binary": "tool",
    }
    with mock.patch("calkit.install.subprocess.run", side_effect=fake_run):
        assert install.install("suite") is True
        del registry["suite"]["binary"]
        assert install.install("suite") is False
    # A prerequisite that's already installed isn't reinstalled, even where
    # it isn't on PATH yet
    ran.clear()
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    with mock.patch("calkit.install.subprocess.run", side_effect=fake_run):
        assert install.install("tool") is True
    assert ran == ["install-tool"]
    # Prompting asks about the prerequisite before the tool, each on its
    # own prompt
    (fake_bin / "prereq").unlink()
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "y"

    with (
        mock.patch("builtins.input", side_effect=fake_input),
        mock.patch("calkit.install.install", return_value=True) as m_install,
    ):
        assert install.prompt_and_install("tool", interactive=True) is True
    assert [p.split("'")[1] for p in prompts] == ["prereq", "tool"]
    assert [c.args[0] for c in m_install.call_args_list] == ["prereq", "tool"]
    # A versioned install directory is found through a glob, newest last
    for version in ("R-4.9.0", "R-4.10.0"):
        vbin = tmp_dir / version / "bin"
        vbin.mkdir(parents=True)
        (vbin / "R").write_text("#!/bin/sh\nexit 0\n")
        (vbin / "R").chmod(0o755)
    registry["R"] = {
        "script": "install-r",
        "path_add": str(tmp_dir / "R-*" / "bin"),
    }
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    with mock.patch("calkit.install.subprocess.run", side_effect=fake_run):
        assert install.install("R") is True
    assert os.environ["PATH"].startswith(str(tmp_dir / "R-4.10.0" / "bin"))
    # An app with no installer on this platform still says what to run
    monkeypatch.setattr("calkit.install.get_installer", lambda app: None)
    with (
        mock.patch("calkit.install.sys.platform", "linux"),
        mock.patch("calkit.core.check_dep_exists", return_value=False),
        pytest.raises(ValueError, match="package manager"),
    ):
        calkit.check_system_deps(
            ck_info={"dependencies": ["R"]}, interactive=False
        )
    # The listing marks what Calkit installed
    from typer.testing import CliRunner

    from calkit.cli.main.core import app as calkit_app

    monkeypatch.setattr(
        "calkit.install.read_install_log",
        lambda: [{"app": "pixi", "installed_at": "2026-09-16T00:00:00+00:00"}],
    )
    result = CliRunner().invoke(calkit_app, ["list", "installers"])
    assert result.exit_code == 0
    assert "pixi  [installed by Calkit 2026-09-16" in result.output
