"""Tests for the ``dvc`` module."""

import os
import subprocess

import calkit


def test_get_remotes(tmp_dir):
    subprocess.call(["git", "init"])
    assert not calkit.dvc.get_remotes()
    subprocess.call(["dvc", "init"])
    assert not calkit.dvc.get_remotes()
    subprocess.call(
        [
            "dvc",
            "remote",
            "add",
            "something",
            "https://sup.com",
        ]
    )
    subprocess.call(
        [
            "dvc",
            "remote",
            "add",
            "something-very-long-remote-that-will-be-more-than-one-line",
            "https://sup.com/this/is/a/long/remote/url/so/test/this",
        ]
    )
    resp = calkit.dvc.get_remotes()
    assert resp == {
        "something": "https://sup.com",
        "something-very-long-remote-that-will-be-more-than-one-line": (
            "https://sup.com/this/is/a/long/remote/url/so/test/this"
        ),
    }


def test_hash_directory():
    this_dir = os.path.dirname(__file__)
    fpath = os.path.join(this_dir, "..", "..", "test", "dvc-md5-dir")
    res = calkit.dvc.hash_directory(fpath)
    assert res["nfiles"] == 1
    assert res["size"] == 1226
    assert res["hash"] == "md5"
    assert res["md5"] == "ca2ffab71e00d528b974e583d789ec97.dir"
