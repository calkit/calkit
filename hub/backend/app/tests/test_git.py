"""Tests for app.git."""

import concurrent.futures
import json
import os
import random
import subprocess
from contextlib import contextmanager
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


def test_git_tree_is_thread_safe(tmp_path):
    """Concurrent reads through one GitTree return uncorrupted content.

    GitPython funnels every object read through a single persistent
    `git cat-file --batch` subprocess and documents `stream_object_data` as
    not thread-safe. Without serialization, fanning figure resolution across
    a thread pool interleaves readers on that one pipe: reads come back as
    another blob's bytes, raise "SHA ... could not be resolved", or hang.
    """
    repo_dir = tmp_path / "repo"
    repo, _ = _init_repo(repo_dir)
    # Incompressible content, so the blobs stay large on disk and each read
    # spans several pipe buffers -- that's what gives concurrent readers the
    # chance to interleave. Repetitive filler would zlib down to a few bytes
    # per object and read atomically, hiding the bug. Nested directories make
    # each lookup walk intermediate tree objects too.
    rand = random.Random(0)
    expected = {}
    for d in ("a", "b", "c"):
        (repo_dir / "figures" / d).mkdir(parents=True, exist_ok=True)
        for i in range(8):
            path = f"figures/{d}/f{i}.bin"
            content = rand.randbytes(200_000)
            (repo_dir / path).write_bytes(content)
            expected[path] = content
    repo.git.add(["figures"])
    repo.git.commit(["-m", "Add figures"])

    tree = app.git.GitTree(repo, repo.head.commit.hexsha)

    def read(path: str) -> tuple[str, bytes]:
        # Mirrors how get_contents_from_tree touches the tree per figure.
        tree.is_symlink(path)
        tree.is_file(path + ".dvc")
        return path, tree.read_bytes(path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(read, list(expected)))

    assert len(results) == len(expected)
    for path, content in results:
        assert content == expected[path], f"{path} came back corrupted"


class _StubProject:
    def __init__(self, name: str) -> None:
        self.owner_github_name = "ck-test-owner"
        self.name = name
        self.git_repo_url = "https://github.com/ck-test-owner/" + name
        self.github_repo = "ck-test-owner/" + name
        self.is_public = True
        self.id = None


def test_get_repo_requires_a_completed_clone(tmp_path, monkeypatch):
    import shutil as _shutil

    from filelock import Timeout

    from app.config import settings

    project = _StubProject(f"ck-repo-ready-{random.randint(0, 10**9)}")
    base_dir = os.path.join(
        settings.CLONE_ROOT,
        "anonymous",
        project.owner_github_name,
        project.name,
    )
    repo_dir = os.path.join(base_dir, "repo")
    updated_fpath = os.path.join(base_dir, "updated.txt")
    monkeypatch.setattr(app.git, "record_project_update", lambda *a, **k: None)
    clones: list[list[str]] = []
    # Captured before patching: everything else get_repo shells out to (the
    # `touch` of the marker file) still has to really run.
    real_check_call = app.git.subprocess.check_call

    # Stand in for the network clone: make a real repo where one was asked
    # for, so everything downstream of the clone behaves normally.
    def fake_check_call(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            clones.append(cmd)
            target = cmd[-1]
            os.makedirs(target, exist_ok=True)
            r = git.Repo.init(target)
            r.git.config(["user.name", "CI Test"])
            r.git.config(["user.email", "ci-test@example.com"])
            (Path(target) / "notes.txt").write_text("one\n")
            r.git.add(["notes.txt"])
            r.git.commit(["-m", "Init"])
            return 0
        return real_check_call(cmd, *args, **kwargs)

    monkeypatch.setattr(app.git.subprocess, "check_call", fake_check_call)
    try:
        # A first read clones, and the marker that says so is written
        repo = app.git.get_repo(
            project=project, user=None, session=None, ttl=600
        )
        assert os.path.isfile(updated_fpath)
        assert len(clones) == 1
        assert repo.head.commit is not None
        # A second read within the TTL reuses that clone rather than
        # re-cloning
        app.git.get_repo(project=project, user=None, session=None, ttl=600)
        assert len(clones) == 1
        # A tree left behind by a clone that died partway has no marker, so
        # it is thrown away and fetched again rather than read as if it were
        # complete
        os.remove(updated_fpath)
        (Path(repo_dir) / "half-written.txt").write_text("junk\n")
        app.git.get_repo(project=project, user=None, session=None, ttl=600)
        assert len(clones) == 2
        assert not (Path(repo_dir) / "half-written.txt").exists()
        # While another worker holds the lock for its own first clone, there
        # is nothing safe to read: say so rather than serving an empty tree
        os.remove(updated_fpath)

        class _HeldLock:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def __enter__(self):
                raise Timeout("held")

            def __exit__(self, *args) -> None:
                pass

        monkeypatch.setattr(app.git, "FileLock", _HeldLock)
        with pytest.raises(HTTPException) as excinfo:
            app.git.get_repo(project=project, user=None, session=None, ttl=600)
        assert excinfo.value.status_code == 503
    finally:
        _shutil.rmtree(base_dir, ignore_errors=True)


def test_get_repo_clone_failures_leave_nothing_readable(tmp_path, monkeypatch):
    import shutil as _shutil
    import subprocess as _subprocess

    from app.config import settings

    project = _StubProject(f"ck-repo-fail-{random.randint(0, 10**9)}")
    base_dir = os.path.join(
        settings.CLONE_ROOT,
        "anonymous",
        project.owner_github_name,
        project.name,
    )
    repo_dir = os.path.join(base_dir, "repo")
    updated_fpath = os.path.join(base_dir, "updated.txt")
    monkeypatch.setattr(app.git, "record_project_update", lambda *a, **k: None)
    real_check_call = app.git.subprocess.check_call
    outcome: dict[str, str] = {"mode": "timeout"}

    # A clone that writes some of the repo and then fails, which is what a
    # timeout or a dropped connection actually looks like on disk.
    def fake_check_call(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            target = cmd[-1]
            os.makedirs(target, exist_ok=True)
            (Path(target) / "partial.pack").write_text("half a repo")
            if outcome["mode"] == "timeout":
                raise _subprocess.TimeoutExpired(cmd, 1)
            raise _subprocess.CalledProcessError(128, cmd)
        return real_check_call(cmd, *args, **kwargs)

    monkeypatch.setattr(app.git.subprocess, "check_call", fake_check_call)
    try:
        # A repo too big to finish inside the budget reports that, rather
        # than surfacing as a server error
        with pytest.raises(HTTPException) as excinfo:
            app.git.get_repo(project=project, user=None, session=None, ttl=600)
        assert excinfo.value.status_code == 504
        # Nothing half-written is left where a reader would find it, so the
        # next attempt starts clean instead of inheriting the wreckage
        assert not os.path.isdir(repo_dir)
        assert not os.path.isdir(repo_dir + ".cloning")
        assert not os.path.isfile(updated_fpath)
        # A repo that isn't there at all is still a 404
        outcome["mode"] = "missing"
        with pytest.raises(HTTPException) as excinfo:
            app.git.get_repo(project=project, user=None, session=None, ttl=600)
        assert excinfo.value.status_code == 404
        assert not os.path.isdir(repo_dir)
    finally:
        _shutil.rmtree(base_dir, ignore_errors=True)


def test_get_repo_applies_the_configured_clone_filter(monkeypatch):
    import shutil as _shutil

    from app.config import settings

    project = _StubProject(f"ck-repo-filter-{random.randint(0, 10**9)}")
    base_dir = os.path.join(
        settings.CLONE_ROOT,
        "anonymous",
        project.owner_github_name,
        project.name,
    )
    monkeypatch.setattr(app.git, "record_project_update", lambda *a, **k: None)
    real_check_call = app.git.subprocess.check_call
    commands: list[list[str]] = []

    def fake_check_call(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            commands.append(cmd)
            target = cmd[-1]
            os.makedirs(target, exist_ok=True)
            r = git.Repo.init(target)
            r.git.config(["user.name", "CI Test"])
            r.git.config(["user.email", "ci-test@example.com"])
            (Path(target) / "notes.txt").write_text("one")
            r.git.add(["notes.txt"])
            r.git.commit(["-m", "Init"])
            return 0
        return real_check_call(cmd, *args, **kwargs)

    monkeypatch.setattr(app.git.subprocess, "check_call", fake_check_call)
    try:
        # Most of a full clone of a project that keeps its results in Git is
        # old revisions nobody asked for, so the filter is passed through
        monkeypatch.setattr(settings, "GIT_CLONE_FILTER", "blob:limit=1m")
        app.git.get_repo(project=project, user=None, session=None, ttl=600)
        assert "--filter=blob:limit=1m" in commands[0]
        # The clone lands at its final name only once git is done with it,
        # so no reader ever sees a partly written tree
        assert commands[0][-1].endswith(".cloning")
        assert os.path.isdir(os.path.join(base_dir, "repo"))
        assert not os.path.isdir(os.path.join(base_dir, "repo.cloning"))
        # Empty means a full clone, for a deployment that needs reads to
        # work without reaching the remote
        _shutil.rmtree(base_dir, ignore_errors=True)
        monkeypatch.setattr(settings, "GIT_CLONE_FILTER", "")
        app.git.get_repo(project=project, user=None, session=None, ttl=600)
        assert not any(a.startswith("--filter") for a in commands[1])
    finally:
        _shutil.rmtree(base_dir, ignore_errors=True)


def test_shared_read_checkout_is_shared_and_never_written(monkeypatch):
    import shutil as _shutil

    from app.config import settings

    project = _StubProject(f"ck-shared-{random.randint(0, 10**9)}")
    monkeypatch.setattr(app.git, "record_project_update", lambda *a, **k: None)
    real_check_call = app.git.subprocess.check_call
    clones: list[str] = []

    def fake_check_call(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            target = cmd[-1]
            clones.append(target)
            os.makedirs(target, exist_ok=True)
            r = git.Repo.init(target)
            r.git.config(["user.name", "CI Test"])
            r.git.config(["user.email", "ci-test@example.com"])
            (Path(target) / "notes.txt").write_text("one")
            r.git.add(["notes.txt"])
            r.git.commit(["-m", "Init"])
            return 0
        return real_check_call(cmd, *args, **kwargs)

    monkeypatch.setattr(app.git.subprocess, "check_call", fake_check_call)
    shared_base = os.path.join(
        settings.CLONE_ROOT,
        app.git.SHARED_READER_DIR,
        project.owner_github_name,
        project.name,
    )
    anon_base = os.path.join(
        settings.CLONE_ROOT,
        "anonymous",
        project.owner_github_name,
        project.name,
    )
    try:
        # A public project reads from one copy, so a second reader finds
        # it already there
        repo = app.git.get_repo(
            project=project,
            user=None,
            session=None,
            ttl=600,
            read_only=True,
        )
        assert app.git.SHARED_READER_DIR in str(repo.working_dir)
        assert len(clones) == 1
        app.git.get_repo(
            project=project,
            user=None,
            session=None,
            ttl=600,
            read_only=True,
        )
        assert len(clones) == 1
        # A write that lands there is refused, not authored in a tree
        # others are reading
        assert app.git.is_shared_read_checkout(repo)
        with pytest.raises(HTTPException) as excinfo:
            app.git.refuse_if_shared(repo)
        assert excinfo.value.status_code == 500
        # Git refuses too, so a write bypassing our helpers is stopped
        hooks_dir = os.path.join(str(repo.working_dir), ".git", "hooks")
        for hook in app.git._SHARED_HOOKS:
            assert os.access(os.path.join(hooks_dir, hook), os.X_OK)
        (Path(str(repo.working_dir)) / "notes.txt").write_text("two")
        repo.git.add(["notes.txt"])
        with pytest.raises(git.exc.GitCommandError):
            repo.git.commit(["-m", "Should never land"])
        repo.git.reset(["--hard"])
        # Not asking for it gets the caller its own copy, exactly as before
        own = app.git.get_repo(
            project=project, user=None, session=None, ttl=600
        )
        assert app.git.SHARED_READER_DIR not in str(own.working_dir)
        assert not app.git.is_shared_read_checkout(own)
        assert len(clones) == 2
        # A private project with no App installation keeps its own copy
        project.is_public = False
        monkeypatch.setattr(
            app.github,
            "get_app_installation_token",
            lambda *a, **k: (_ for _ in ()).throw(
                app.github.GitHubAppNotConfigured("no app")
            ),
        )
        private = app.git.get_repo(
            project=project,
            user=None,
            session=None,
            ttl=600,
            read_only=True,
        )
        assert app.git.SHARED_READER_DIR not in str(private.working_dir)
        # The account names that would land a writable checkout somewhere
        # it must never go are renamed rather than trusted
        assert app.git._clone_dir_segment("octocat") == "octocat"
        for hostile in ("..", ".", "", app.git.SHARED_READER_DIR):
            segment = app.git._clone_dir_segment(hostile)
            assert segment.startswith("acct_")
            assert segment != app.git.SHARED_READER_DIR
        assert app.git._clone_dir_segment("a/b") == "a_b"
        # Stable across calls
        assert app.git._clone_dir_segment("..") == app.git._clone_dir_segment(
            ".."
        )
    finally:
        _shutil.rmtree(shared_base, ignore_errors=True)
        _shutil.rmtree(anon_base, ignore_errors=True)


def test_working_tree_refuses_paths_outside_the_checkout(tmp_path):
    # Two checkouts side by side, the way CLONE_ROOT holds them
    victim = tmp_path / "_shared" / "victim-owner" / "victim-proj" / "repo"
    ours = tmp_path / "_shared" / "us" / "our-proj" / "repo"
    victim.mkdir(parents=True)
    ours.mkdir(parents=True)
    (victim / "private.csv").write_text("secret,data\n")
    (ours / "ours.csv").write_text("ours\n")
    tree = app.git.WorkingTree(str(ours))
    # Our own files read normally
    assert tree.is_file("ours.csv")
    assert tree.read_bytes("ours.csv") == b"ours\n"
    assert tree.size("ours.csv") == 5
    assert "ours.csv" in tree.listdir(None)
    # Walking out finds nothing, however it is spelled
    escapes = [
        "../../../victim-owner/victim-proj/repo/private.csv",
        "a/../../../../victim-owner/victim-proj/repo/private.csv",
        str(victim / "private.csv"),
    ]
    for path in escapes:
        assert not tree.is_file(path)
        assert not tree.exists(path)
        assert not tree.is_safe_symlink(path)
        with pytest.raises(HTTPException) as excinfo:
            tree.read_bytes(path)
        assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException):
        tree.listdir("../../../victim-owner/victim-proj/repo")
    # Repo plumbing is not project content, however it is spelled, but a
    # name that merely starts with ".git" is
    (ours / ".gitignore").write_text("*.pyc\n")
    for internal in (".git", ".git/config", "a/../.git/config"):
        assert not tree.is_file(internal)
        with pytest.raises(HTTPException):
            tree.read_bytes(internal)
    # A symlink is the spelling that survives normalization, so the
    # resolved path is checked too
    (ours / "link").symlink_to(".git")
    with pytest.raises(HTTPException):
        tree.read_bytes("link/config")
    assert tree.read_bytes(".gitignore") == b"*.pyc\n"
    # A symlink is the other way out, so content reads resolve
    (ours / "link.csv").symlink_to(victim / "private.csv")
    assert tree.is_file("link.csv")
    assert not tree.is_safe_symlink("link.csv")
    with pytest.raises(HTTPException):
        tree.read_bytes("link.csv")
    # One that stays inside still reads
    (ours / "inside.csv").symlink_to(ours / "ours.csv")
    assert tree.is_safe_symlink("inside.csv")
    assert tree.read_bytes("inside.csv") == b"ours\n"


def test_remote_head_cache_is_bypassed_when_the_caller_wants_the_truth(
    tmp_path,
):
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.check_call(
        ["git", "init", "--bare", "-q", "-b", "main", str(origin)]
    )
    subprocess.check_call(["git", "init", "-q", "-b", "main", str(seed)])
    for k, v in (("user.email", "ci@example.com"), ("user.name", "CI")):
        subprocess.check_call(["git", "-C", str(seed), "config", k, v])
    (seed / "f.txt").write_text("v1\n")
    subprocess.check_call(["git", "-C", str(seed), "add", "f.txt"])
    subprocess.check_call(["git", "-C", str(seed), "commit", "-qm", "v1"])
    subprocess.check_call(
        ["git", "-C", str(seed), "remote", "add", "origin", str(origin)]
    )
    subprocess.check_call(
        ["git", "-C", str(seed), "push", "-q", "origin", "main"]
    )
    clone = tmp_path / "clone"
    subprocess.check_call(["git", "clone", "-q", str(origin), str(clone)])
    repo = git.Repo(str(clone))
    old = repo.head.commit.hexsha
    # A read before the push leaves the pre-push head in the cache
    assert app.git.get_remote_head_sha(repo, str(origin), "main") == old
    (seed / "f.txt").write_text("v2\n")
    subprocess.check_call(["git", "-C", str(seed), "commit", "-qam", "v2"])
    subprocess.check_call(
        ["git", "-C", str(seed), "push", "-q", "origin", "main"]
    )
    new = (
        subprocess.check_output(["git", "-C", str(seed), "rev-parse", "HEAD"])
        .decode()
        .strip()
    )
    assert new != old
    # A cached read still answers with the old head, which is what let a
    # push land without the warm it queued ever fetching it
    assert app.git.get_remote_head_sha(repo, str(origin), "main") == old
    # ttl=0/None callers ask the remote instead, and refresh the cache
    assert (
        app.git.get_remote_head_sha(repo, str(origin), "main", use_cache=False)
        == new
    )
    assert app.git.get_remote_head_sha(repo, str(origin), "main") == new


def _fake_overleaf_clone(files: dict[str, str]):
    """Stand in for the clone, writing *files* into the destination."""

    def clone(cmd, **kwargs):
        dest = cmd[-1]
        for rel, text in files.items():
            full = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(full) or dest, exist_ok=True)
            with open(full, "w") as f:
                f.write(text)

    return clone


def _read_title(files: dict[str, str]):
    from unittest.mock import patch

    from app.git import read_overleaf_title

    with (
        patch("app.git.users.get_overleaf_token", return_value="tok"),
        patch(
            "app.git.subprocess.check_call",
            side_effect=_fake_overleaf_clone(files),
        ),
    ):
        return read_overleaf_title(
            user=object(), session=object(), overleaf_project_id="abc"
        )


def test_read_overleaf_title_finds_the_document_that_builds() -> None:
    # The file with a document class wins over an included fragment that
    # happens to sort first.
    title = _read_title(
        {
            "aaa-intro.tex": "\\section{Intro}\nNo class here.\n",
            "main.tex": (
                "\\documentclass{article}\n"
                "\\title{Coherent structures in boundary layers}\n"
                "\\begin{document}\\maketitle\\end{document}\n"
            ),
        }
    )
    assert title == "Coherent structures in boundary layers"


def test_read_overleaf_title_prefers_a_conventional_name() -> None:
    doc = "\\documentclass{article}\n\\title{%s}\n"
    title = _read_title(
        {"appendix.tex": doc % "Appendix", "paper.tex": doc % "The paper"}
    )
    assert title == "The paper"


def test_read_overleaf_title_returns_none_when_there_is_none() -> None:
    assert _read_title({"main.tex": "\\documentclass{article}\n"}) is None
    # Nothing that builds at all
    assert _read_title({"notes.tex": "\\section{Notes}\n"}) is None
    assert _read_title({}) is None


def test_read_overleaf_title_collapses_whitespace() -> None:
    title = _read_title(
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\title{A title\n  split over lines}\n"
            )
        }
    )
    assert title == "A title split over lines"


def _commit(repo: git.Repo, name: str, text: str) -> str:
    """Write a file and commit it, returning the new SHA."""
    (Path(str(repo.working_dir)) / name).write_text(text)
    repo.git.add([name])
    repo.git.commit(["-m", f"Write {name}"])
    return repo.head.commit.hexsha


def _identify(repo: git.Repo) -> None:
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])


def test_push_and_expire_updates_the_shared_checkout(tmp_path) -> None:
    """A write lands in the shared checkout without going via the remote."""
    from unittest.mock import patch

    project = _StubProject("ck-shared-push")
    # An origin, the checkout everyone reads, and the writer's own clone,
    # laid out the way get_repo lays them out
    origin_dir = tmp_path / "origin.git"
    git.Repo.init(str(origin_dir), bare=True)
    seed_dir = tmp_path / "seed"
    seed = git.Repo.clone_from(str(origin_dir), str(seed_dir))
    _identify(seed)
    first = _commit(seed, "notes.txt", "one")
    seed.git.push(["origin", seed.active_branch.name])
    branch = seed.active_branch.name
    shared_root = tmp_path / "_shared"
    shared_base = shared_root / project.owner_github_name / project.name
    shared_base.mkdir(parents=True)
    shared = git.Repo.clone_from(str(origin_dir), str(shared_base / "repo"))
    (shared_base / "updated.txt").touch()
    os.utime(shared_base / "updated.txt", (0, 0))
    # What a warm left there: data DVC pulled, which is gitignored, and so
    # isn't the checkout's to lose when the tree is rewritten under it
    (shared_base / "repo" / "data").mkdir()
    (shared_base / "repo" / "data" / "raw.csv").write_text("x,y\n1,2\n")
    writer_dir = tmp_path / "writer"
    writer = git.Repo.clone_from(str(origin_dir), str(writer_dir))
    _identify(writer)
    _commit(writer, ".gitignore", "data/\n")
    second = _commit(writer, "notes.txt", "two")
    assert shared.head.commit.hexsha == first

    with (
        patch("app.git.shared_reader_root", return_value=str(shared_root)),
        patch("app.git.cache.set_json") as set_json,
    ):
        app.git.push_and_expire(project, writer, branch)
        # The remote is where we put it, and every clone's cached answer
        # for that says so
        assert set_json.call_args.args[1] == second

    # Origin has it, and so does the shared checkout -- in its working tree,
    # not just its refs, since that is what a read actually looks at
    assert git.Repo(str(origin_dir)).commit(branch).hexsha == second
    shared = git.Repo(str(shared_base / "repo"))
    assert shared.head.commit.hexsha == second
    assert (shared_base / "repo" / "notes.txt").read_text() == "two"
    # The pulled data is still there: a rewrite of the tracked tree isn't a
    # reason to make the next read pull a gigabyte of it again
    assert (shared_base / "repo" / "data" / "raw.csv").exists()
    # And it is marked current, so the next read doesn't refresh it at all
    assert (shared_base / "updated.txt").stat().st_mtime > 0


def test_a_read_after_a_write_touches_the_network_not_at_all(
    tmp_path, monkeypatch
) -> None:
    """The point of pushing into the shared checkout, stated as a test.

    Counts what a read does rather than how long it takes: the saving is
    one ``ls-remote`` and one ``fetch``, both round trips to GitHub, and
    both are gone only if the read makes neither.
    """
    from unittest.mock import patch

    project = _StubProject("ck-shared-no-network")
    origin_dir = tmp_path / "origin.git"
    git.Repo.init(str(origin_dir), bare=True)
    seed_dir = tmp_path / "seed"
    seed = git.Repo.clone_from(str(origin_dir), str(seed_dir))
    _identify(seed)
    _commit(seed, "notes.txt", "one")
    branch = seed.active_branch.name
    seed.git.push(["origin", branch])
    shared_root = tmp_path / "_shared"
    shared_base = shared_root / project.owner_github_name / project.name
    shared_base.mkdir(parents=True)
    git.Repo.clone_from(str(origin_dir), str(shared_base / "repo"))
    (shared_base / "updated.txt").touch()
    writer_dir = tmp_path / "writer"
    writer = git.Repo.clone_from(str(origin_dir), str(writer_dir))
    _identify(writer)
    monkeypatch.setattr(app.git, "record_project_update", lambda *a, **k: None)

    ops: list[str] = []
    real_timed = app.git._timed

    @contextmanager
    def recording_timed(operation: str, **fields):
        ops.append(operation)
        with real_timed(operation, **fields):
            yield

    def read() -> git.Repo:
        ops.clear()
        with patch("app.git._timed", recording_timed):
            return app.git.get_repo(
                project=project,
                user=None,
                session=None,
                ttl=60,
                read_only=True,
            )

    with patch("app.git.shared_reader_root", return_value=str(shared_root)):
        # A read first, so the read-only hooks are in place before the
        # write -- a push into a checkout that refuses writes is exactly
        # the case worth proving
        read()
        second = _commit(writer, "notes.txt", "two")
        app.git.push_and_expire(project, writer, branch)
        repo = read()
        assert repo.head.commit.hexsha == second
        assert (Path(str(repo.working_dir)) / "notes.txt").read_text() == "two"
        assert ops == [], f"a read after a write did {ops}"

        # For contrast, the path taken when the local push can't be made:
        # the same read asks where the remote is and goes and gets it
        third = _commit(writer, "notes.txt", "three")
        writer.git.push(["origin", branch])
        app.git.expire_shared_read_clone(project, branch)
        repo = read()
        assert repo.head.commit.hexsha == third
        assert "ls-remote" in ops and "fetch" in ops


def test_push_and_expire_falls_back_when_the_shared_checkout_wont_take_it(
    tmp_path,
) -> None:
    """Anything that stops the local push leaves the old slow path."""
    from unittest.mock import patch

    project = _StubProject("ck-shared-push-fallback")
    origin_dir = tmp_path / "origin.git"
    git.Repo.init(str(origin_dir), bare=True)
    seed_dir = tmp_path / "seed"
    seed = git.Repo.clone_from(str(origin_dir), str(seed_dir))
    _identify(seed)
    _commit(seed, "notes.txt", "one")
    branch = seed.active_branch.name
    seed.git.push(["origin", branch])
    shared_root = tmp_path / "_shared"
    shared_base = shared_root / project.owner_github_name / project.name
    shared_base.mkdir(parents=True)
    shared = git.Repo.clone_from(str(origin_dir), str(shared_base / "repo"))
    (shared_base / "updated.txt").touch()
    # The shared checkout is off on some other branch, so a push of `branch`
    # would move the ref without rewriting the tree a read looks at
    shared.git.checkout(["-b", "somewhere-else"])
    writer_dir = tmp_path / "writer"
    writer = git.Repo.clone_from(str(origin_dir), str(writer_dir))
    _identify(writer)
    second = _commit(writer, "notes.txt", "two")

    with (
        patch("app.git.shared_reader_root", return_value=str(shared_root)),
        patch("app.git.cache.set_json"),
    ):
        app.git.push_and_expire(project, writer, branch)

    # The write still went to origin, and the checkout is marked stale so
    # the next read fetches it -- which is what happened before any of this
    assert git.Repo(str(origin_dir)).commit(branch).hexsha == second
    assert (shared_base / "updated.txt").stat().st_mtime == 0


def test_push_and_expire_leaves_a_dirty_shared_checkout_alone(
    tmp_path,
) -> None:
    """A tree that doesn't match its head is not ours to overwrite."""
    from unittest.mock import patch

    project = _StubProject("ck-shared-push-dirty")
    origin_dir = tmp_path / "origin.git"
    git.Repo.init(str(origin_dir), bare=True)
    seed_dir = tmp_path / "seed"
    seed = git.Repo.clone_from(str(origin_dir), str(seed_dir))
    _identify(seed)
    _commit(seed, "notes.txt", "one")
    branch = seed.active_branch.name
    seed.git.push(["origin", branch])
    shared_root = tmp_path / "_shared"
    shared_base = shared_root / project.owner_github_name / project.name
    shared_base.mkdir(parents=True)
    git.Repo.clone_from(str(origin_dir), str(shared_base / "repo"))
    (shared_base / "updated.txt").touch()
    # Something left a tracked file edited there. Git refuses to rewrite
    # the tree over it, which is the answer we want: the edit is evidence
    # something is wrong, and losing it would hide that.
    (shared_base / "repo" / "notes.txt").write_text("edited by hand")
    writer_dir = tmp_path / "writer"
    writer = git.Repo.clone_from(str(origin_dir), str(writer_dir))
    _identify(writer)
    second = _commit(writer, "notes.txt", "two")

    with (
        patch("app.git.shared_reader_root", return_value=str(shared_root)),
        patch("app.git.cache.set_json"),
    ):
        app.git.push_and_expire(project, writer, branch)

    assert git.Repo(str(origin_dir)).commit(branch).hexsha == second
    assert (shared_base / "repo" / "notes.txt").read_text() == "edited by hand"
    # Marked stale, so the next read fetches and resets it the old way
    assert (shared_base / "updated.txt").stat().st_mtime == 0


def test_push_and_expire_without_a_shared_checkout_leaves_nothing_stale(
    tmp_path,
) -> None:
    """Nobody has read the project yet, so there is nothing to catch up."""
    from unittest.mock import patch

    project = _StubProject("ck-shared-push-absent")
    origin_dir = tmp_path / "origin.git"
    git.Repo.init(str(origin_dir), bare=True)
    writer_dir = tmp_path / "writer"
    writer = git.Repo.clone_from(str(origin_dir), str(writer_dir))
    _identify(writer)
    head = _commit(writer, "notes.txt", "one")
    branch = writer.active_branch.name
    shared_root = tmp_path / "_shared"

    with (
        patch("app.git.shared_reader_root", return_value=str(shared_root)),
        patch("app.git.cache.set_json") as set_json,
    ):
        app.git.push_and_expire(project, writer, branch)
        assert set_json.call_args.args[1] == head
    assert git.Repo(str(origin_dir)).commit(branch).hexsha == head
    # The first read clones, and it clones what was just pushed
    assert not (shared_root / project.owner_github_name).exists()


def test_expire_shared_read_clone_records_a_known_head(tmp_path) -> None:
    """A push knows where the remote is, so the next read needn't ask."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from app import cache
    from app.git import expire_shared_read_clone

    project = SimpleNamespace(
        owner_github_name="o",
        name="p",
        git_repo_url="https://github.com/o/p",
    )
    marker_dir = tmp_path / "o" / "p"
    marker_dir.mkdir(parents=True)
    (marker_dir / "updated.txt").touch()
    key = cache.make_key("remote-head", "https://github.com/o/p.git", "main")
    with (
        patch("app.git.shared_reader_root", return_value=str(tmp_path)),
        patch("app.git.cache.set_json") as set_json,
        patch("app.git.cache.delete") as delete,
    ):
        expire_shared_read_clone(project, "main", head="a" * 40)
        set_json.assert_called_once_with(key, "a" * 40, ttl=300)
        delete.assert_not_called()
    # Without one, the next read still has to go and ask.
    with (
        patch("app.git.shared_reader_root", return_value=str(tmp_path)),
        patch("app.git.cache.set_json") as set_json,
        patch("app.git.cache.delete") as delete,
    ):
        expire_shared_read_clone(project, "main")
        delete.assert_called_once_with(key)
        set_json.assert_not_called()
    # Either way the checkout is marked stale, so the next read refreshes it.
    assert (marker_dir / "updated.txt").stat().st_mtime == 0
