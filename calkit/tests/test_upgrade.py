"""Tests for ``calkit.upgrade``."""

import subprocess
import sys

import pytest

import calkit
from calkit import upgrade


def test_get_install_method(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    assert upgrade.get_install_method() == "pip"
    (tmp_path / "pipx_metadata.json").write_text("{}")
    assert upgrade.get_install_method() == "pipx"
    (tmp_path / "uv-receipt.toml").write_text("")
    assert upgrade.get_install_method() == "uv-tool"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert upgrade.get_install_method() == "frozen"
    with pytest.raises(ValueError, match="standalone"):
        upgrade.get_upgrade_cmd()


def test_check(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(calkit, "__version__", "1.0.0")
    spawned = []

    def popen_detached(cmd, cwd=None, **kws):
        # Never from the project, which could shadow calkit
        assert cwd == str(tmp_path / ".calkit")
        spawned.append(cmd)

    monkeypatch.setattr(upgrade, "_popen_detached", popen_detached)
    # Skipped under test and in CI
    upgrade.check("status")
    monkeypatch.delenv("CALKIT_ENV")
    monkeypatch.setenv("CI", "true")
    upgrade.check("status")
    assert not spawned
    monkeypatch.delenv("CI")
    # And when upgrading by hand
    upgrade.check("upgrade")
    assert not spawned
    # The first command starts a check, and later ones the same day don't
    upgrade.check("status")
    assert len(spawned) == 1
    assert spawned[0][1:3] == ["-m", "calkit.upgrade"]
    upgrade.check("status")
    assert len(spawned) == 1
    assert not capsys.readouterr().err
    # A newer version is announced once a day
    upgrade.update_state(latest="1.1.0")
    upgrade.check("status")
    assert "v1.1.0 is available" in capsys.readouterr().err
    upgrade.check("status")
    assert not capsys.readouterr().err
    # But not while an upgrade to it is underway
    upgrade.update_state(notified=0, upgrading=upgrade.time.time())
    upgrade.check("status")
    assert not capsys.readouterr().err
    # An upgrade is reported once it's taken effect
    upgrade.update_state(upgraded_from="0.9.0")
    upgrade.check("status")
    assert "upgraded from v0.9.0 to v1.0.0" in capsys.readouterr().err
    assert "upgraded_from" not in upgrade.read_state()
    # Nothing is shown when nobody's at a terminal
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    upgrade.update_state(upgraded_from="0.9.0")
    upgrade.check("status")
    assert not capsys.readouterr().err
    assert upgrade.read_state()["upgraded_from"] == "0.9.0"
    # A day later, another check starts
    upgrade.update_state(checked=0)
    upgrade.check("status")
    assert len(spawned) == 2
    # Unless checking is turned off, which also drops what it last found
    monkeypatch.setenv("CALKIT_AUTO_UPGRADE", "no-check")
    upgrade.update_state(checked=0, latest="1.1.0")
    upgrade.check("status")
    assert len(spawned) == 2
    assert upgrade.read_state()["latest"] is None


def test_check_in_background(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    monkeypatch.setattr(calkit, "__version__", "1.0.0")
    monkeypatch.setattr(upgrade, "get_latest_version", lambda: "1.1.0")
    monkeypatch.setattr(upgrade, "is_dev_install", lambda: False)
    monkeypatch.setattr(upgrade, "can_auto_upgrade", lambda: True)
    monkeypatch.setattr(upgrade, "get_upgrade_cmd", lambda: ["up"])
    monkeypatch.setattr(upgrade, "get_calkit_pids", lambda: [2])
    runs = []
    monkeypatch.setattr(
        upgrade, "run_after_exit", lambda cmds, pids: runs.append((cmds, pids))
    )
    # Turned off, a new version is only recorded so it can be announced
    monkeypatch.setenv("CALKIT_TEST_AUTO_UPGRADE", "off")
    upgrade.check_in_background([1])
    assert upgrade.read_state()["latest"] == "1.1.0"
    assert not runs
    # On by default, it upgrades once the command that started it exits,
    # and on Windows this process too, since it holds files the upgrade
    # replaces
    monkeypatch.delenv("CALKIT_TEST_AUTO_UPGRADE")
    upgrade.check_in_background([1])
    pids = [1, 2] if sys.platform == "win32" else [1]
    assert runs == [([["up"]], pids)]
    assert upgrade.read_state()["upgraded_from"] == "1.0.0"
    # Nothing happens when already up to date
    monkeypatch.setattr(upgrade, "get_latest_version", lambda: "1.0.0")
    upgrade.check_in_background([1])
    assert len(runs) == 1
    # Or for installs Calkit doesn't own, which are only notified
    monkeypatch.setattr(upgrade, "get_latest_version", lambda: "1.2.0")
    monkeypatch.setattr(upgrade, "can_auto_upgrade", lambda: False)
    upgrade.check_in_background([1])
    assert len(runs) == 1
    assert upgrade.read_state()["latest"] == "1.2.0"
    # Dev installs are left alone entirely
    monkeypatch.setattr(upgrade, "is_dev_install", lambda: True)
    monkeypatch.setattr(upgrade, "get_latest_version", lambda: "1.3.0")
    upgrade.check_in_background([1])
    assert upgrade.read_state()["latest"] == "1.2.0"
    # For real, the upgrade runs once the command exits, rather than this
    # process waiting on itself
    if sys.platform == "win32":
        return
    monkeypatch.undo()
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    monkeypatch.setattr(calkit, "__version__", "1.0.0")
    monkeypatch.setattr(upgrade, "get_latest_version", lambda: "1.1.0")
    monkeypatch.setattr(upgrade, "is_dev_install", lambda: False)
    monkeypatch.setattr(upgrade, "can_auto_upgrade", lambda: True)
    marker = tmp_path / "upgraded"
    monkeypatch.setattr(
        upgrade, "get_upgrade_cmd", lambda: ["touch", str(marker)]
    )
    cmd = subprocess.Popen(["sleep", "1"])
    upgrade.check_in_background([cmd.pid])
    assert cmd.poll() is not None
    assert marker.exists()


def test_get_dev_upgrade_cmds(tmp_path, monkeypatch):
    def git(cwd, *args):
        subprocess.check_call(["git", "-C", str(cwd), *args])

    origin = tmp_path / "origin"
    git(tmp_path, "init", "-q", "-b", "main", str(origin))
    git(origin, "commit", "-q", "--allow-empty", "-m", "init")
    git(origin, "branch", "feature")
    git(origin, "branch", "other")
    repo = tmp_path / "repo"
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    git(repo, "checkout", "-q", "-b", "local")
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "feature")
    monkeypatch.setattr(upgrade, "get_editable_path", lambda: str(repo))
    monkeypatch.setattr(upgrade, "get_install_method", lambda: "uv-tool")
    monkeypatch.setattr("shutil.which", lambda x: x)
    python = f"{sys.version_info.major}.{sys.version_info.minor}"

    def install(path):
        return [
            "uv",
            "tool",
            "install",
            "--python",
            python,
            "--reinstall-package",
            "calkit-python",
            "--editable",
            str(path),
        ]

    # By default the current branch is reinstalled, with nothing to pull for
    # one that has no upstream
    assert upgrade.get_dev_upgrade_cmds() == [install(repo)]
    # A branch checked out in another worktree is pulled and installed there
    assert upgrade.get_dev_upgrade_cmds("feature") == [
        ["git", "-C", str(wt), "pull", "--ff-only"],
        install(wt),
    ]
    # One checked out nowhere is checked out in place
    assert upgrade.get_dev_upgrade_cmds("main") == [
        ["git", "-C", str(repo), "checkout", "main"],
        ["git", "-C", str(repo), "pull", "--ff-only"],
        install(repo),
    ]
    # One only on the remote gets an upstream when checked out
    assert upgrade.get_dev_upgrade_cmds("other") == [
        ["git", "-C", str(repo), "checkout", "other"],
        ["git", "-C", str(repo), "pull", "--ff-only"],
        install(repo),
    ]
    # A package below the repo root is installed from the same place in
    # whichever worktree
    (repo / "pkg").mkdir()
    monkeypatch.setattr(
        upgrade, "get_editable_path", lambda: str(repo / "pkg")
    )
    assert upgrade.get_dev_upgrade_cmds() == [install(repo / "pkg")]
    assert upgrade.get_dev_upgrade_cmds("feature") == [
        ["git", "-C", str(wt), "pull", "--ff-only"],
        install(wt / "pkg"),
    ]
    # A source outside Git can only be reinstalled
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setattr(upgrade, "get_editable_path", lambda: str(plain))
    assert upgrade.get_dev_upgrade_cmds() == [install(plain)]
    with pytest.raises(ValueError, match="not in a Git repo"):
        upgrade.get_dev_upgrade_cmds("main")
    # Checking out another branch would disturb uncommitted changes
    monkeypatch.setattr(upgrade, "get_editable_path", lambda: str(repo))
    (repo / "new.txt").write_text("hi")
    with pytest.raises(ValueError, match="has changes"):
        upgrade.get_dev_upgrade_cmds("other")
    # Not a dev install
    monkeypatch.setattr(upgrade, "get_editable_path", lambda: None)
    with pytest.raises(ValueError, match="not an editable"):
        upgrade.get_dev_upgrade_cmds()


def test_upgrade_with_operators(tmp_path, monkeypatch, capsys):
    from calkit import operator

    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    requests = []
    running = [("calkit.io", 123), ("other.hub", 456)]

    def request_restarts(stop=False):
        requests.append(stop)
        return running

    monkeypatch.setattr(operator, "request_restarts", request_restarts)
    # Elsewhere, running Operators restart once it's done, which also
    # catches a dev install updated without a new version
    monkeypatch.setattr(sys, "platform", "linux")
    marker = tmp_path / "upgraded"
    upgrade.run_upgrade_cmds([["touch", str(marker)]])
    assert marker.exists()
    assert requests == [False]
    assert "Operators will restart" in capsys.readouterr().out
    # On Windows they stop so their files can be replaced, the upgrade
    # waits for them, and those installed as a service start again either
    # way
    monkeypatch.setattr(sys, "platform", "win32")
    startup = tmp_path / "calkit-operator-calkit.io.vbs"
    startup.write_text("")
    monkeypatch.setattr(
        operator,
        "_windows_startup_path",
        lambda key: str(startup if key == "calkit.io" else tmp_path / "none"),
    )
    started = []
    monkeypatch.setattr(
        upgrade, "_popen_detached", lambda cmd, **kw: started.append(cmd)
    )
    requests.clear()
    assert upgrade.run_after_exit([["up"]], [1]) == ["calkit.io", "other.hub"]
    assert requests == [True]
    script = started[0][-1]
    for pid in [1, 123, 456]:
        assert f"Wait-Process -Id {pid} " in script
    assert script.index("& 'up'") < script.index(f"& wscript '{startup}'")
    assert script.count("wscript") == 1
    assert script.endswith("exit $failed")
