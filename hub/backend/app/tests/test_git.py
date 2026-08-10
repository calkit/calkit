"""Tests for app.git."""

import json
from pathlib import Path

import git
import pytest
from fastapi import HTTPException

import app.git
import app.github
import app.projects


class _FakeResp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload)


@pytest.fixture(autouse=True)
def _clear_installation_token_cache():
    """Keep the in-process App installation-token cache from leaking between
    tests (a cached token would skip the mocked GitHub calls)."""
    app.github._installation_token_cache.clear()
    yield
    app.github._installation_token_cache.clear()


def _init_repo(repo_dir: Path) -> tuple[git.Repo, str]:
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    notes = repo_dir / "notes.txt"
    notes.write_text("version-one\n")
    repo.git.add(["notes.txt"])
    repo.git.commit(["-m", "Add v1 notes"])
    ref_v1 = repo.head.commit.hexsha
    notes.write_text("version-two\n")
    (repo_dir / "new-file.txt").write_text("new\n")
    repo.git.add(["notes.txt", "new-file.txt"])
    repo.git.commit(["-m", "Update notes and add new file"])
    return repo, ref_v1


def test_get_file_history_git_tracked(tmp_path, monkeypatch):
    """get_file_history returns commits that touched the given file."""
    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    _, ref_v1 = _init_repo(tmp_path / "repo")
    repo = git.Repo(tmp_path / "repo")
    history = app.git.get_file_history(repo, path="notes.txt")
    # notes.txt was changed in both commits
    assert len(history) >= 2
    hashes = [c["short_hash"] for c in history]
    assert ref_v1[:7] in hashes
    # Entries are newest-first
    assert history[0]["committed_date"] >= history[-1]["committed_date"]


def test_get_file_history_missing_file(tmp_path, monkeypatch):
    """get_file_history returns an empty list for a file with no history."""
    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    _init_repo(tmp_path / "repo")
    repo = git.Repo(tmp_path / "repo")
    history = app.git.get_file_history(repo, path="nonexistent.txt")
    assert history == []


def test_get_file_history_dvc_pointer(tmp_path, monkeypatch):
    """get_file_history finds commits via a .dvc pointer file."""
    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])

    # Simulate a DVC-tracked file: only the .dvc pointer is in git.
    pointer_v1 = repo_dir / "data.csv.dvc"
    pointer_v1.write_text("md5: abc123\npath: data.csv\n")
    repo.git.add(["data.csv.dvc"])
    repo.git.commit(["-m", "Track data.csv with DVC v1"])
    ref_v1 = repo.head.commit.hexsha

    pointer_v1.write_text("md5: def456\npath: data.csv\n")
    repo.git.add(["data.csv.dvc"])
    repo.git.commit(["-m", "Update data.csv v2"])

    history = app.git.get_file_history(repo, path="data.csv", storage="dvc")
    hashes = [c["hash"] for c in history]
    assert ref_v1 in hashes
    assert len(history) == 2
    # Newest first
    assert history[0]["committed_date"] >= history[-1]["committed_date"]


def test_get_file_history_dvc_lock(tmp_path, monkeypatch):
    """get_file_history detects md5 transitions in dvc.lock."""
    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])

    dvc_lock = repo_dir / "dvc.lock"

    # Commit 1: output appears for the first time.
    dvc_lock.write_text(
        "schema: '2.0'\nstages:\n  train:\n    outs:\n    - path: model.pkl\n      md5: aaa111\n"
    )
    repo.git.add(["dvc.lock"])
    repo.git.commit(["-m", "Add model.pkl in dvc.lock"])
    ref_v1 = repo.head.commit.hexsha

    # Commit 2: unrelated change — md5 unchanged, should NOT appear.
    dvc_lock.write_text(
        "schema: '2.0'\nstages:\n  train:\n    outs:\n    - path: model.pkl\n      md5: aaa111\n  other:\n    outs: []\n"
    )
    repo.git.add(["dvc.lock"])
    repo.git.commit(["-m", "Add unrelated stage"])

    # Commit 3: md5 changed — should appear.
    dvc_lock.write_text(
        "schema: '2.0'\nstages:\n  train:\n    outs:\n    - path: model.pkl\n      md5: bbb222\n"
    )
    repo.git.add(["dvc.lock"])
    repo.git.commit(["-m", "Retrain model"])
    ref_v3 = repo.head.commit.hexsha

    history = app.git.get_file_history(repo, path="model.pkl", storage="dvc")
    hashes = [c["hash"] for c in history]
    assert ref_v1 in hashes, "First appearance commit must be in history"
    assert ref_v3 in hashes, "Updated md5 commit must be in history"
    # The unrelated commit should not be included.
    assert len(history) == 2
    # Newest first
    assert history[0]["committed_date"] >= history[-1]["committed_date"]


def test_get_app_installation_token(monkeypatch) -> None:
    """The App JWT is exchanged for a repo-scoped installation token."""
    calls: dict = {}
    monkeypatch.setattr(app.github, "create_app_token", lambda: "fake-jwt")

    def fake_get(url, headers=None, timeout=None):
        calls["get_url"] = url
        calls["get_auth"] = headers["Authorization"]
        return _FakeResp(200, {"id": 12345})

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["post_url"] = url
        calls["post_json"] = json
        return _FakeResp(201, {"token": "ghs_installationtoken"})

    monkeypatch.setattr(app.github.requests, "get", fake_get)
    monkeypatch.setattr(app.github.requests, "post", fake_post)
    token = app.github.get_app_installation_token("owner-acct", "my-repo")
    assert token == "ghs_installationtoken"
    assert calls["get_url"].endswith("/repos/owner-acct/my-repo/installation")
    assert calls["get_auth"] == "Bearer fake-jwt"
    assert "/app/installations/12345/access_tokens" in calls["post_url"]
    assert calls["post_json"] == {"repositories": ["my-repo"]}


def test_get_app_installation_token_caches(monkeypatch) -> None:
    """A second call reuses the cached token instead of minting again."""
    mint_count = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        mint_count["n"] += 1
        return _FakeResp(200, {"id": 12345})

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResp(
            201,
            {"token": "ghs_tok", "expires_at": "2999-01-01T00:00:00Z"},
        )

    monkeypatch.setattr(app.github, "create_app_token", lambda: "fake-jwt")
    monkeypatch.setattr(app.github.requests, "get", fake_get)
    monkeypatch.setattr(app.github.requests, "post", fake_post)
    first = app.github.get_app_installation_token("acme", "widget")
    second = app.github.get_app_installation_token("acme", "widget")
    assert first == second == "ghs_tok"
    # Minted only once; the second call was served from the cache.
    assert mint_count["n"] == 1


def test_get_app_installation_token_no_installation(monkeypatch) -> None:
    """A missing installation surfaces as a 502, not a crash."""
    monkeypatch.setattr(app.github, "create_app_token", lambda: "fake-jwt")
    monkeypatch.setattr(
        app.github.requests,
        "get",
        lambda *a, **k: _FakeResp(404, {}),
    )
    with pytest.raises(HTTPException) as exc:
        app.github.get_app_installation_token("owner", "repo")
    assert exc.value.status_code == 502


def test_get_ck_info_from_repo_valid(tmp_path):
    """A well-formed calkit.yaml is loaded into a dict."""
    repo, _ = _init_repo(tmp_path / "repo")
    (tmp_path / "repo" / "calkit.yaml").write_text(
        "owner: someone\nname: proj\n"
    )
    ck_info = app.git.get_ck_info_from_repo(repo)
    assert ck_info["name"] == "proj"


def test_get_ck_info_from_repo_malformed_yaml(tmp_path):
    """A malformed calkit.yaml degrades to an empty dict rather than raising.

    A user repo with multiple YAML documents in one calkit.yaml previously
    raised a ruamel ComposerError that bubbled up as a 500 on the project
    page. It should be treated as empty instead.
    """
    repo, _ = _init_repo(tmp_path / "repo")
    # Two YAML documents in a single file triggers a ComposerError.
    (tmp_path / "repo" / "calkit.yaml").write_text(
        "owner: someone\n---\nname: proj\n"
    )
    assert app.git.get_ck_info_from_repo(repo) == {}
