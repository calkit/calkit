"""Tests for ``calkit.github``."""

import subprocess

import calkit


def test_can_use_ssh(monkeypatch):
    def answer(stderr="", raises=None):
        def run(cmd, *args, **kwargs):
            # Never asks anything unless interactive
            assert ("BatchMode=yes" in cmd) == (kwargs["timeout"] is not None)
            if raises:
                raise raises
            return subprocess.CompletedProcess(cmd, 1, "", stderr)

        monkeypatch.setattr("subprocess.run", run)

    # GitHub greets an accepted key, exiting with 1 since it gives no shell
    answer("Hi me! You've successfully authenticated, but GitHub does not")
    assert calkit.github.can_use_ssh()
    answer("git@github.com: Permission denied (publickey).")
    assert not calkit.github.can_use_ssh()
    # No ssh, or no answer in time, isn't SSH being set up
    answer(raises=FileNotFoundError("ssh"))
    assert not calkit.github.can_use_ssh()
    answer(raises=subprocess.TimeoutExpired("ssh", 15))
    assert not calkit.github.can_use_ssh()
