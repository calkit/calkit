"""Tests for the ``dvc`` module."""

import subprocess

import calkit


def test_get_remotes(tmp_dir):
    subprocess.call(["git", "init"])
    assert not calkit.dvc.get_remotes()
    subprocess.call([sys.executable, "-m", "dvc", "init"])
    assert not calkit.dvc.get_remotes()
    subprocess.call(
        [
            sys.executable,
            "-m",
            "dvc",
            "remote",
            "add",
            "something",
            "https://sup.com",
        ]
    )
    resp = calkit.dvc.get_remotes()
    assert resp == {"something": "https://sup.com"}
