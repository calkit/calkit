"""Tests for the ``overleaf`` module."""

import json
import os
import subprocess

import git
import pytest

import calkit


def _commit_all(repo: git.Repo, message: str) -> None:
    repo.git.add(["-A"])
    repo.git.commit(["-m", message])


def test_get_sync_status(tmp_dir):
    subprocess.run(["calkit", "init"], check=True)
    repo = git.Repo()
    os.makedirs(os.path.join("paper", "figures"))
    with open(os.path.join("paper", "main.tex"), "w") as f:
        f.write(
            "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n"
        )
    fig_path = os.path.join("paper", "figures", "fig.png")
    with open(fig_path, "wb") as fb:
        fb.write(b"figure version 1")
    ck_info = calkit.load_calkit_info()
    ck_info["figures"] = [
        {"path": "paper/figures/fig.png", "title": "A figure"}
    ]
    ck_info["overleaf_sync"] = {
        "paper": {"url": "https://www.overleaf.com/project/abc123"}
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    _commit_all(repo, "Add paper")
    # Stand up a repo to stand in for the Overleaf project, which starts out
    # with only the TeX file, so the figure has never been pushed
    overleaf_dir = tmp_dir / "overleaf"
    os.makedirs(overleaf_dir)
    overleaf_repo = git.Repo.init(path=overleaf_dir)
    with open(os.path.join(overleaf_dir, "main.tex"), "w") as f:
        f.write(
            "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n"
        )
    _commit_all(overleaf_repo, "Initial commit")
    sync_info = calkit.overleaf.get_sync_info()["paper"]
    assert sync_info["project_id"] == "abc123"
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    assert status["overleaf_project_id"] == "abc123"
    assert not status["in_sync"]
    assert status["commits_from_overleaf"] == 0
    pushes = {f["path"]: f for f in status["files_to_push"]}
    assert pushes["figures/fig.png"]["state"] == "new"
    assert pushes["figures/fig.png"]["figure"]
    assert pushes["figures/fig.png"]["project_path"] == "paper/figures/fig.png"
    # The TeX file matches on both sides, so it isn't pending a push, and
    # wouldn't be flagged as a figure regardless
    assert "main.tex" not in pushes
    # Push the figure by hand to represent a completed sync
    os.makedirs(os.path.join(overleaf_dir, "figures"))
    with open(os.path.join(overleaf_dir, "figures", "fig.png"), "wb") as fb:
        fb.write(b"figure version 1")
    _commit_all(overleaf_repo, "Add figure")
    sync_info["last_sync_commit"] = overleaf_repo.head.commit.hexsha
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    assert status["in_sync"]
    assert status["files_to_push"] == []
    assert status["files_to_delete"] == []
    # Regenerating the figure locally leaves Overleaf out of date
    with open(fig_path, "wb") as fb:
        fb.write(b"figure version 2, which is longer")
    _commit_all(repo, "Update figure")
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    assert not status["in_sync"]
    pushes = {f["path"]: f for f in status["files_to_push"]}
    assert pushes["figures/fig.png"]["state"] == "modified"
    assert pushes["figures/fig.png"]["figure"]
    # A same-size edit still counts as modified, since sizes only serve to
    # skip reading files that obviously match
    with open(fig_path, "wb") as fb:
        fb.write(b"figure version 3, which is longer")
    _commit_all(repo, "Update figure again")
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    assert [f["path"] for f in status["files_to_push"]] == ["figures/fig.png"]
    # Edits made on Overleaf show up as commits waiting to come back
    with open(os.path.join(overleaf_dir, "main.tex"), "a") as f:
        f.write("\n% Edited in Overleaf\n")
    _commit_all(overleaf_repo, "Edit on Overleaf")
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    assert status["commits_from_overleaf"] == 1
    assert status["overleaf_commit"] == overleaf_repo.head.commit.hexsha
    assert status["project_commit"] == repo.head.commit.hexsha
    # A file removed from the project should be deleted from Overleaf
    os.remove(fig_path)
    ck_info = calkit.load_calkit_info()
    ck_info["figures"] = []
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    _commit_all(repo, "Remove figure")
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    deletes = [f["path"] for f in status["files_to_delete"]]
    assert deletes == ["figures/fig.png"]
    assert status["files_to_delete"][0]["figure"]


def test_write_sync_info_without_calkit_dir(tmp_dir):
    """A repo that has never used Calkit locally has no ``.calkit`` dir.

    That is the hub's normal case: it clones a project and imports an
    Overleaf document into it, so nothing has created the directory yet.
    """
    fpath = calkit.overleaf.write_sync_info(
        synced_path="paper",
        info={"project_id": "abc123"},
        wdir=os.getcwd(),
    )
    assert os.path.isfile(fpath)
    with open(fpath) as f:
        written = json.load(f)
    assert written["paper"]["project_id"] == "abc123"


def test_pull(tmp_dir):
    # Stand up a repo for the Overleaf project and clone it
    overleaf_dir = tmp_dir / "overleaf"
    overleaf_repo = git.Repo.init(overleaf_dir)
    (overleaf_dir / "main.tex").write_text("v1")
    _commit_all(overleaf_repo, "Initial commit")
    clone = git.Repo.clone_from(overleaf_dir, tmp_dir / "clone")
    clone_dir = tmp_dir / "clone"
    # Leave the clone diverged and dirty, like after a sync whose push failed,
    # with a conflicting edit made on Overleaf in the meantime
    (clone_dir / "main.tex").write_text("local")
    _commit_all(clone, "Sync with Calkit project")
    (clone_dir / "main.tex").write_text("uncommitted")
    (clone_dir / "leftover.tex").write_text("untracked")
    (clone_dir / ".gitignore").write_text("*.bib\n")
    (clone_dir / "refs.bib").write_text("ignored")
    (overleaf_dir / "main.tex").write_text("v2")
    _commit_all(overleaf_repo, "Edit on Overleaf")
    calkit.overleaf.pull(clone)
    assert clone.head.commit == overleaf_repo.head.commit
    assert (clone_dir / "main.tex").read_text() == "v2"
    assert not (clone_dir / "leftover.tex").exists()
    assert not (clone_dir / "refs.bib").exists()
    assert not clone.is_dirty(untracked_files=True)
    # A fetch failure should show Git's error, without the token, and only
    # give token advice for authentication failures
    clone.git.remote("set-url", "origin", f"file://{tmp_dir}/missing")
    with pytest.raises(RuntimeError) as e:
        calkit.overleaf.pull(clone)
    msg = str(e.value)
    assert "Failed to pull from Overleaf" in msg
    assert "missing" in msg
    assert "overleaf_token" not in msg
    clone.git.remote(
        "set-url", "origin", "https://git:secret@127.0.0.1:9/project"
    )
    with pytest.raises(RuntimeError) as e:
        calkit.overleaf.pull(clone)
    msg = str(e.value)
    assert "127.0.0.1" in msg
    assert "secret" not in msg
    # Overleaf rejecting the token should be told apart from other failures
    rejected = git.GitCommandError(
        ["git", "fetch"],
        128,
        stderr="fatal: Authentication failed for 'https://git.overleaf.com/x/'",
    )
    err = calkit.overleaf._git_error(rejected, "pull")
    assert isinstance(err, calkit.overleaf.AuthError)
    assert "expired" in str(err)
    assert not isinstance(
        calkit.overleaf._git_error(
            git.GitCommandError(["git", "fetch"], 128, stderr="nope"), "pull"
        ),
        calkit.overleaf.AuthError,
    )


def test_lock(tmp_dir):
    from filelock import FileLock, Timeout

    lock_path = calkit.overleaf.get_project_dir("abc123") + ".lock"
    # Another process can't take the lock while a sync holds it
    with calkit.overleaf.lock("abc123"):
        with pytest.raises(Timeout):
            FileLock(lock_path).acquire(timeout=0)
    # It's released afterwards, even if the sync fails
    with pytest.raises(RuntimeError):
        with calkit.overleaf.lock("abc123"):
            raise RuntimeError("Sync failed")
    other = FileLock(lock_path)
    other.acquire(timeout=0)
    other.release()


def test_web_client():
    import io
    import zipfile
    from types import SimpleNamespace

    def response(text="", status=200, url="https://www.overleaf.com/x", **kw):
        return SimpleNamespace(
            ok=status < 400,
            status_code=status,
            url=url,
            text=text,
            content=kw.get("content", text.encode()),
            json=lambda: kw.get("json"),
        )

    class Http:
        def __init__(self, responses):
            self.responses = responses
            self.requests = []

        def request(self, method, url, **kwargs):
            self.requests.append((method, url, kwargs))
            for (m, part), resp in self.responses.items():
                if m == method and part in url:
                    return resp() if callable(resp) else resp
            return response()

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

        def delete(self, url, **kwargs):
            return self.request("DELETE", url, **kwargs)

    client = calkit.overleaf.WebClient("overleaf_session2=abc ")
    assert client.http.cookies["overleaf_session2"] == "abc"
    # The CSRF token comes from the project dashboard
    page = '<meta name="ol-csrfToken" content="tok123">'
    client.http = Http({("GET", "/project"): response(page)})
    assert client.csrf_token == "tok123"
    # A session Overleaf doesn't accept is sent to the login page
    client = calkit.overleaf.WebClient("expired")
    client.http = Http(
        {("GET", "/project"): response(url="https://www.overleaf.com/login")}
    )
    with pytest.raises(calkit.overleaf.AuthError):
        client.csrf_token
    # Downloads must actually be zip archives
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("main.tex", "Hi")
    client.http = Http(
        {("GET", "/download/zip"): response(content=buf.getvalue())}
    )
    assert client.download("p1") == buf.getvalue()
    client.http = Http({("GET", "/download/zip"): response("<html>")})
    with pytest.raises(calkit.overleaf.AuthError):
        client.download("p1")
    # The file tree arrives over socket.io long polling, possibly after
    # other messages, framed together, including a heartbeat to answer
    root = {"_id": "root", "docs": [], "fileRefs": [], "folders": []}
    join = json.dumps(
        {
            "name": "joinProjectResponse",
            "args": [{"project": {"rootFolder": [root]}}],
        }
    )
    accepted = '5:::{"name":"connectionAccepted"}'
    frames = [
        "1::",
        f"�{len(accepted)}�{accepted}�3�2::",
        f"5:::{join}",
    ]
    client.http = Http(
        {
            ("GET", "/socket.io/1/xhr-polling/sid9"): lambda: response(
                frames.pop(0)
            ),
            ("GET", "/socket.io/1/"): response("sid9:60:60:xhr-polling"),
        }
    )
    assert client.get_root_folder("p1") == root
    sent = [
        (m, kw.get("data")) for m, _, kw in client.http.requests if m == "POST"
    ]
    assert sent == [("POST", "2::"), ("POST", "0::")]
    assert all(
        kw["params"]["projectId"] == "p1"
        for m, _, kw in client.http.requests
        if m == "GET"
    )
    rejected = '5:::{"name":"connectionRejected","args":["not authorized"]}'
    client.http = Http(
        {
            ("GET", "/socket.io/1/xhr-polling/"): response(rejected),
            ("GET", "/socket.io/1/"): response("sid9:60:60:xhr-polling"),
        }
    )
    with pytest.raises(calkit.overleaf.AuthError):
        client.get_root_folder("p1")
    # Uploads go to the root folder, with Overleaf creating any folders on
    # the way to the file
    client.csrf_token = "tok123"
    client.http = Http({("POST", "/upload"): response(json={"success": True})})
    client.upload("p1", "root", "figs/a.png", b"png")
    _, url, kw = client.http.requests[0]
    assert url.endswith("/project/p1/upload")
    assert kw["params"] == {"folder_id": "root"}
    assert kw["data"] == {"name": "a.png", "relativePath": "figs/a.png"}
    assert kw["files"]["qqfile"][1] == b"png"
    assert kw["headers"]["X-CSRF-Token"] == "tok123"
    client.upload("p1", "root", "main.tex", b"Hi")
    assert client.http.requests[1][2]["data"] == {"name": "main.tex"}
    client.http = Http(
        {
            ("POST", "/upload"): response(
                json={"success": False, "error": "invalid_filename"}
            )
        }
    )
    with pytest.raises(RuntimeError, match="invalid_filename"):
        client.upload("p1", "root", "bad", b"")
    # Entities are found by path for deleting
    tree = {
        "docs": [{"name": "main.tex", "_id": "d1"}],
        "fileRefs": [],
        "folders": [
            {
                "name": "figs",
                "docs": [],
                "fileRefs": [{"name": "a.png", "_id": "f1"}],
                "folders": [],
            }
        ],
    }
    assert calkit.overleaf._find_entity(tree, "main.tex") == ("doc", "d1")
    assert calkit.overleaf._find_entity(tree, "figs/a.png") == ("file", "f1")
    assert calkit.overleaf._find_entity(tree, "figs/b.png") is None
    assert calkit.overleaf._find_entity(tree, "other/a.png") is None
