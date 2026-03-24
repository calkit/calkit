"""Tests for ``calkit.cli.update`` release updates."""

from __future__ import annotations

import subprocess

import git

import calkit
from calkit.cli.update import update_release


def _init_release_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["git", "config", "user.email", "test@example.com"])
    subprocess.check_call(["git", "config", "user.name", "Test User"])
    with open("README.md", "w") as f:
        f.write("# Test project\n")
    ck_info = {
        "name": "test-project",
        "owner": "calkit",
        "title": "Test project",
        "releases": {
            "v0.1.0": {
                "kind": "project",
                "path": ".",
                "date": "2026-01-01",
                "publisher": "zenodo",
                "record_id": "12345",
                "doi": "10.0000/example",
                "description": "Initial release",
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo = git.Repo()
    repo.git.add(["README.md", "calkit.yaml"])
    repo.git.commit(["-m", "Initial commit"])


def test_update_release_publish_checks_reproducibility(tmp_path, monkeypatch):
    _init_release_project(tmp_path, monkeypatch)
    check_calls = []

    def _fake_check(path=".", verbose=False):
        check_calls.append((path, verbose))

    monkeypatch.setattr(
        calkit.releases, "check_release_reproducibility", _fake_check
    )
    monkeypatch.setattr(calkit.invenio, "post", lambda *args, **kwargs: {})
    update_release(
        name="v0.1.0",
        publish=True,
        no_github=True,
        no_push_tags=True,
    )
    assert check_calls == [(".", False)]
    assert "v0.1.0" in [tag.name for tag in git.Repo().tags]


def test_update_release_reupload_checks_reproducibility(tmp_path, monkeypatch):
    _init_release_project(tmp_path, monkeypatch)
    check_calls = []

    def _fake_check(path=".", verbose=False):
        check_calls.append((path, verbose))

    class _Resp:
        status_code = 200

    monkeypatch.setattr(
        calkit.releases, "check_release_reproducibility", _fake_check
    )
    archive_checks = []
    monkeypatch.setattr(
        calkit.releases,
        "check_project_release_archive",
        lambda zip_path, verbose=False: archive_checks.append(
            (zip_path, verbose)
        ),
    )
    monkeypatch.setattr(calkit.releases, "ls_files", lambda: ["README.md"])
    monkeypatch.setattr(calkit.releases, "make_dvc_md5s", lambda **kwargs: {})
    monkeypatch.setattr(
        calkit.invenio,
        "get",
        lambda *args, **kwargs: {"entries": []},
    )
    monkeypatch.setattr(calkit.invenio, "post", lambda *args, **kwargs: {})
    monkeypatch.setattr(calkit.invenio, "delete", lambda *args, **kwargs: None)
    monkeypatch.setattr(calkit.invenio, "put", lambda *args, **kwargs: _Resp())
    update_release(name="v0.1.0", reupload=True)
    assert check_calls == [(".", False)]
    assert archive_checks == [
        (
            ".calkit/releases/v0.1.0/files/archive.zip",
            False,
        )
    ]
