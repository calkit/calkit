"""Tests for app.git."""

import concurrent.futures
import json
import os
import random
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
