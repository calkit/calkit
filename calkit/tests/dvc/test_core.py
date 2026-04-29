"""Tests for the ``dvc`` module."""

import os
import subprocess

import dvc.repo
import git
from configobj import ConfigObj
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
    fpath = os.path.join(this_dir, "..", "..", "..", "test", "dvc-md5-dir")
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


def test_detect_calkit_remote_type():
    http_name = calkit.dvc.make_remote_name(use_ck=False)
    ck_name = calkit.dvc.make_remote_name(use_ck=True)
    # Default-named HTTP remote
    assert (
        calkit.dvc.detect_calkit_remote_type(http_name, "https://example.com")
        == "http"
    )
    # Default-named ck remote
    assert (
        calkit.dvc.detect_calkit_remote_type(ck_name, "ck://owner/proj")
        == "ck"
    )
    # External-project remote with ":" suffix
    assert (
        calkit.dvc.detect_calkit_remote_type(
            f"{http_name}:owner/proj", "https://example.com/o/p/dvc"
        )
        == "http"
    )
    assert (
        calkit.dvc.detect_calkit_remote_type(
            f"{ck_name}:owner/proj", "ck://owner/proj"
        )
        == "ck"
    )
    # Unrelated remote name
    assert (
        calkit.dvc.detect_calkit_remote_type("something", "https://sup.com")
        is None
    )
    # Matching name but unknown URL scheme
    assert (
        calkit.dvc.detect_calkit_remote_type(http_name, "ssh://git@host/repo")
        is None
    )


def test_configure_remote_ck_uses_ck_scheme_and_skips_http_auth(monkeypatch):
    monkeypatch.setattr(calkit, "detect_project_name", lambda wdir=None: "o/p")

    class DummyRepo:
        def remote(self):
            return "origin"

    monkeypatch.setattr(git, "Repo", lambda wdir=None: DummyRepo())
    calls = []
    events = []

    def fake_run(argv, cwd=None):
        events.append("run")
        calls.append((argv, cwd))
        return 0

    monkeypatch.setattr(calkit.dvc.core, "run_dvc_command", fake_run)
    monkeypatch.setattr(
        calkit.dvc.core,
        "clear_remote_local_http_auth",
        lambda remote_name=None, wdir=None: events.append("clear"),
    )
    out = calkit.dvc.configure_remote(use_ck=True)
    assert out == calkit.dvc.make_remote_name(use_ck=True)
    assert events and events[0] == "clear"
    assert calls == [
        (
            [
                "remote",
                "add",
                "-d",
                "-f",
                calkit.dvc.make_remote_name(use_ck=True),
                "ck://o/p",
            ],
            None,
        )
    ]


def test_add_external_remote(monkeypatch):
    calls = []
    auth_calls = []
    monkeypatch.setattr(
        calkit.dvc.core,
        "run_dvc_command",
        lambda argv, cwd=None: calls.append((argv, cwd)) or 0,
    )
    monkeypatch.setattr(
        calkit.dvc.core,
        "set_remote_auth",
        lambda name: auth_calls.append(name),
    )
    # HTTP case: builds URL from cloud base, sets custom auth
    monkeypatch.setattr(
        calkit.cloud, "get_base_url", lambda: "https://example.com"
    )
    out = calkit.dvc.add_external_remote("o", "p", use_ck=False)
    http_name = f"{calkit.dvc.make_remote_name(use_ck=False)}:o/p"
    assert out == {
        "name": http_name,
        "url": "https://example.com/projects/o/p/dvc",
    }
    assert calls == [
        (
            [
                "remote",
                "add",
                "-f",
                http_name,
                "https://example.com/projects/o/p/dvc",
            ],
            None,
        ),
        (["remote", "modify", http_name, "auth", "custom"], None),
    ]
    assert auth_calls == [http_name]
    # ck case: builds ck:// URL, skips HTTP auth modify and set_remote_auth
    calls.clear()
    auth_calls.clear()
    out = calkit.dvc.add_external_remote("o", "p", use_ck=True)
    ck_name = f"{calkit.dvc.make_remote_name(use_ck=True)}:o/p"
    assert out == {"name": ck_name, "url": "ck://o/p"}
    assert calls == [
        (["remote", "add", "-f", ck_name, "ck://o/p"], None),
    ]
    assert auth_calls == []


def test_set_remote_auth_ck_remote_clears_local_http_auth(
    monkeypatch, tmp_path
):
    remote_name = calkit.dvc.make_remote_name()
    monkeypatch.setattr(
        calkit.dvc.core,
        "get_remotes",
        lambda wdir=None: {remote_name: "ck://owner/proj"},
    )
    dvc_dir = tmp_path / ".dvc"
    dvc_dir.mkdir()
    fpath = dvc_dir / "config.local"
    with open(fpath, "w") as f:
        f.write(
            f'[remote "{remote_name}"]\n'
            "    custom_auth_header = Authorization\n"
            "    password = Bearer token\n"
            "    url = https://example.com\n"
        )
    calkit.dvc.set_remote_auth(wdir=str(tmp_path))
    cfg = ConfigObj(str(fpath), encoding="utf-8")
    section = cfg[f'remote "{remote_name}"']
    assert "custom_auth_header" not in section
    assert "password" not in section
    assert section["url"] == "https://example.com"  # type: ignore
