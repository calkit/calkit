"""Tests for the ``dvc`` module."""

import os
import subprocess

import dvc.repo
from dvc.config_schema import SCHEMA, Invalid
from dvc_objects.fs import known_implementations

import calkit
from calkit.dvc import register_ck_scheme


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


def test_register_ck_scheme_updates_schema_and_registry():
    register_ck_scheme()

    remote_validator = SCHEMA["remote"][str]
    validated = remote_validator({"url": "ck://owner/project"})

    assert validated["url"] == "ck://owner/project"
    assert "ck" in known_implementations


def test_ck_url_rejected_before_registration_when_schema_reset(monkeypatch):
    from dvc.config_schema import REMOTE_SCHEMAS, ByUrl

    original_remote = SCHEMA["remote"]
    try:
        sc = dict(REMOTE_SCHEMAS)
        sc.pop("ck", None)
        SCHEMA["remote"] = {str: ByUrl(sc)}
        validator = SCHEMA["remote"][str]
        try:
            validator({"url": "ck://owner/project"})
            assert False, "Expected Invalid for unsupported scheme"
        except Invalid:
            pass
    finally:
        SCHEMA["remote"] = original_remote


def test_list_files_paths(tmp_dir):
    subprocess.call(["calkit", "init"])
    calkit.dvc.list_files()
    with open("file1.txt", "w") as f:
        f.write("hello")
    repo = dvc.repo.Repo()
    repo.add("file1.txt")  # type: ignore
    assert "file1.txt" in calkit.dvc.list_paths()
