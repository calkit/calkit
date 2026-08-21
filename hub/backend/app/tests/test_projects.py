"""Tests for app.projects."""

import base64
import uuid
from pathlib import Path

import git
import pytest
from sqlmodel import Session

import app.projects
from app.models import Account, Project


def _make_project() -> Project:
    account = Account(
        id=uuid.uuid4(),
        name="owneracct",
        github_name="ownergh",
        user_id=uuid.uuid4(),
    )
    return Project(
        id=uuid.uuid4(),
        name="project-name",
        title="Project Name",
        git_repo_url="https://github.com/ownergh/project-name",
        owner_account_id=account.id,
        owner_account=account,
    )


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


def test_get_project_case_insensitive(db: Session) -> None:
    account = Account(
        id=uuid.uuid4(),
        name="casetest-owner",
        github_name="CaseTest-Owner",
    )
    project = Project(
        id=uuid.uuid4(),
        name="my-project",
        title="My Project",
        git_repo_url="https://github.com/CaseTest-Owner/my-project",
        owner_account_id=account.id,
        owner_account=account,
    )
    db.add(account)
    db.add(project)
    db.commit()
    # Exact match works
    found = app.projects.get_project(
        session=db, owner_name="casetest-owner", project_name="my-project"
    )
    assert found.id == project.id
    # Mixed-case owner and project name both resolve correctly
    found_mixed = app.projects.get_project(
        session=db, owner_name="CASETEST-OWNER", project_name="My-Project"
    )
    assert found_mixed.id == project.id
    # Clean up
    db.delete(project)
    db.delete(account)
    db.commit()


def test_get_project_with_caps_in_account_name(db: Session) -> None:
    from app import users
    from app.models import UserCreate

    suffix = uuid.uuid4().hex[:8]
    account_name = f"CapsUser-{suffix}"
    caps_user = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"{account_name}@example.com",
            password="CapsPassword123",
            account_name=account_name,
            github_username=account_name,
        ),
    )
    project = Project(
        name="caps-project",
        title="Caps Project",
        git_repo_url=f"https://github.com/{account_name}/caps-project",
        owner_account_id=caps_user.account.id,
    )
    db.add(project)
    db.commit()
    try:
        # The stored name is lowercased; display_name preserves original casing.
        assert caps_user.account.name == account_name.lower()
        assert caps_user.account.display_name == account_name
        found = app.projects.get_project(
            session=db, owner_name=account_name, project_name="caps-project"
        )
        assert found.owner_account.display_name == account_name
        found_lower = app.projects.get_project(
            session=db,
            owner_name=account_name.lower(),
            project_name="caps-project",
        )
        assert found_lower.id == found.id
    finally:
        db.delete(project)
        db.delete(caps_user)
        db.commit()


def test_get_project_logged_in_without_min_access_level(db: Session) -> None:
    """A logged-in member can fetch a project with no min access level.

    Regression: the min_access_level check ran unconditionally for
    authenticated users, so the default ``min_access_level=None`` did
    ``access_levels[None]`` and raised KeyError. That broke release viewing for
    project members (the owner saw "release unavailable" for their own release).
    """
    from app import users
    from app.models import UserCreate

    suffix = uuid.uuid4().hex[:8]
    name = f"member-{suffix}"
    owner = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"{name}@example.com",
            password="MemberPassword123",
            account_name=name,
            github_username=name,
        ),
    )
    project = Project(
        name="member-view-project",
        title="Member View Project",
        git_repo_url=f"https://github.com/{name}/member-view-project",
        owner_account_id=owner.account.id,
    )
    db.add(project)
    db.commit()
    try:
        found = app.projects.get_project(
            session=db,
            owner_name=name,
            project_name="member-view-project",
            current_user=owner,
            min_access_level=None,
        )
        assert found.current_user_access == "owner"
    finally:
        db.delete(project)
        db.delete(owner)
        db.commit()


def test_get_contents_from_repo_at_given_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep this test focused on Git ref behavior, not DVC/object storage.
    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    project = _make_project()
    repo, ref_v1 = _init_repo(tmp_path / "repo")
    item_latest = app.projects.get_contents_from_repo(
        project=project,
        repo=repo,
        path="notes.txt",
    )
    assert item_latest.content is not None
    assert (
        base64.b64decode(item_latest.content).decode().strip() == "version-two"
    )
    item_v1 = app.projects.get_contents_from_repo(
        project=project,
        repo=repo,
        path="notes.txt",
        ref=ref_v1,
    )
    assert item_v1.content is not None
    assert base64.b64decode(item_v1.content).decode().strip() == "version-one"
    root_latest = app.projects.get_contents_from_repo(
        project=project, repo=repo
    )
    latest_names = {item.name for item in (root_latest.dir_items or [])}
    assert "new-file.txt" in latest_names
    root_v1 = app.projects.get_contents_from_repo(
        project=project, repo=repo, ref=ref_v1
    )
    v1_names = {item.name for item in (root_v1.dir_items or [])}
    assert "new-file.txt" not in v1_names


def test_get_contents_dvc_pointer_files_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Files tracked by standalone .dvc pointer files appear in directory
    listings with storage='dvc', and their .dvc pointer sibling remains
    visible as a git-tracked file.
    """
    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    project = _make_project()
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    # Create a .dvc pointer file for a file in a subdirectory
    figures_dir = repo_dir / "figures"
    figures_dir.mkdir()
    dvc_pointer = figures_dir / "plot.png.dvc"
    dvc_pointer.write_text(
        "outs:\n"
        "- md5: abc123def456abc123def456abc12345\n"
        "  size: 42000\n"
        "  path: plot.png\n"
    )
    # Also add a regular git-tracked file
    (repo_dir / "README.md").write_text("# Project\n")
    repo.git.add(["."])
    repo.git.commit(["-m", "Add files"])
    # Root listing: figures/ dir should appear
    root_item = app.projects.get_contents_from_repo(project=project, repo=repo)
    root_names = {item.name for item in (root_item.dir_items or [])}
    assert "figures" in root_names
    assert "README.md" in root_names
    # figures/ listing: both plot.png (DVC) and plot.png.dvc (git) appear
    figures_item = app.projects.get_contents_from_repo(
        project=project, repo=repo, path="figures"
    )
    figures_by_name = {
        item.name: item for item in (figures_item.dir_items or [])
    }
    assert "plot.png" in figures_by_name, (
        "DVC-tracked file should appear without .dvc suffix"
    )
    assert "plot.png.dvc" in figures_by_name, (
        ".dvc pointer file should still appear as a git-tracked entry"
    )
    dvc_entry = figures_by_name["plot.png"]
    assert dvc_entry.storage == "dvc"
    assert dvc_entry.size == 42000
    assert dvc_entry.type == "file"
    git_entry = figures_by_name["plot.png.dvc"]
    assert git_entry.storage == "git"


def test_get_contents_dvc_pointer_renamed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A .dvc pointer whose filename differs from outs[0].path is resolved correctly."""
    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    project = _make_project()
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    figures_dir = repo_dir / "figures"
    figures_dir.mkdir()
    # Pointer filename (old_plot.png.dvc) differs from the tracked path (plot.png)
    dvc_pointer = figures_dir / "old_plot.png.dvc"
    dvc_pointer.write_text(
        "outs:\n"
        "- md5: abc123def456abc123def456abc12345\n"
        "  size: 7777\n"
        "  path: plot.png\n"
    )
    repo.git.add(["."])
    repo.git.commit(["-m", "Add renamed pointer"])
    figures_item = app.projects.get_contents_from_repo(
        project=project, repo=repo, path="figures"
    )
    figures_by_name = {
        item.name: item for item in (figures_item.dir_items or [])
    }
    assert "plot.png" in figures_by_name, (
        "DVC-tracked path from outs[0].path should appear, not stripped pointer name"
    )
    assert figures_by_name["plot.png"].storage == "dvc"
    assert figures_by_name["plot.png"].size == 7777


def test_get_contents_dvc_pointer_dir_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A .dvc pointer file whose md5 ends in '.dir' produces a dir entry."""
    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    project = _make_project()
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    # .dvc pointer for a directory (md5 ends with .dir)
    dvc_pointer = repo_dir / "data.dvc"
    dvc_pointer.write_text(
        "outs:\n"
        "- md5: abc123def456abc123def456abc12345.dir\n"
        "  size: 99999\n"
        "  nfiles: 5\n"
        "  path: data\n"
    )
    repo.git.add(["data.dvc"])
    repo.git.commit(["-m", "Add data.dvc pointer"])
    root_item = app.projects.get_contents_from_repo(project=project, repo=repo)
    items_by_name = {item.name: item for item in (root_item.dir_items or [])}
    assert "data" in items_by_name, (
        "DVC-tracked directory should appear without .dvc suffix"
    )
    data_entry = items_by_name["data"]
    assert data_entry.storage == "dvc"
    assert data_entry.type == "dir"
    assert data_entry.size == 99999


def test_declared_paths_with_leading_dot_slash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path declared as "./paper/main.pdf" in calkit.yaml still matches its
    "paper/main.pdf" DVC out.
    """
    monkeypatch.setattr(
        app.projects,
        "expand_dvc_lock_outs",
        lambda *a, **k: {
            "paper/main.pdf": {
                "path": "paper/main.pdf",
                "md5": "604e8206a831104ebcbafc886d81337f",
                "size": 274278,
                "type": "file",
                "dirname": "paper",
                "stage": "build-paper",
            }
        },
    )
    monkeypatch.setattr(
        app.projects, "get_data_fpath_for_md5", lambda **kwargs: None
    )
    project = _make_project()
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    (repo_dir / "calkit.yaml").write_text(
        "publications:\n"
        "  - path: ./paper/main.pdf\n"
        "    title: A paper\n"
        "    stage: build-paper\n"
        "figures:\n"
        "  - path: ./figures/plot.png\n"
        "    title: A figure\n"
        "showcase:\n"
        "  - figure: ./figures/plot.png\n"
    )
    (repo_dir / "dvc.lock").write_text(
        "schema: '2.0'\n"
        "stages:\n"
        "  build-paper:\n"
        "    cmd: calkit latex build paper/main.tex\n"
        "    outs:\n"
        "    - path: paper/main.pdf\n"
        "      md5: 604e8206a831104ebcbafc886d81337f\n"
        "      size: 274278\n"
    )
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Add metadata"])
    # The publication resolves to its DVC out whether it's requested by the
    # path as declared or by the normalized one
    for path in ["./paper/main.pdf", "paper/main.pdf"]:
        item = app.projects.get_contents_from_repo(
            project=project, repo=repo, path=path
        )
        assert item.path == "paper/main.pdf"
        assert item.storage == "dvc"
        assert item.size == 274278
        assert item.stage == "build-paper"
        assert item.calkit_object is not None
        assert item.calkit_object["title"] == "A paper"
    # Declared metadata comes back with normalized paths, so everything
    # downstream keys artifacts the same way DVC and Git do
    ck_info = app.projects.get_ck_info_for_ref(project=project, repo=repo)
    assert ck_info["publications"][0]["path"] == "paper/main.pdf"
    assert ck_info["figures"][0]["path"] == "figures/plot.png"
    assert ck_info["showcase"][0]["figure"] == "figures/plot.png"
    # Lookups by the normalized path find the declared publication
    pub = app.projects.get_publication_from_repo(
        project=project, repo=repo, path="paper/main.pdf"
    )
    assert pub.path == "paper/main.pdf"
    assert pub.storage == "dvc"
    assert pub.stage == "build-paper"


def test_get_notebook_from_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    project = _make_project()
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    # A notebook declared only as a jupyter-notebook pipeline stage, plus one
    # declared in the notebooks list, and one that's simply committed
    (repo_dir / "calkit.yaml").write_text(
        "pipeline:\n"
        "  stages:\n"
        "    report:\n"
        "      kind: jupyter-notebook\n"
        "      notebook_path: notebooks/report.ipynb\n"
        "notebooks:\n"
        "  - path: notebooks/declared.ipynb\n"
        "    title: Declared notebook\n"
    )
    nb_dir = repo_dir / "notebooks"
    nb_dir.mkdir()
    for name in ["report.ipynb", "declared.ipynb", "raw.ipynb"]:
        (nb_dir / name).write_text('{"cells": [], "nbformat": 4}\n')
    # Only the stage notebook has an HTML export committed
    html_dir = repo_dir / ".calkit" / "notebooks" / "html" / "notebooks"
    html_dir.mkdir(parents=True)
    (html_dir / "report.html").write_text("<html>report</html>\n")
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Add notebooks"])
    # The stage-only notebook resolves, prefers its HTML export, and gets its
    # stage attached
    nb = app.projects.get_notebook_from_repo(
        project=project, repo=repo, path="notebooks/report.ipynb"
    )
    assert nb.path == "notebooks/report.ipynb"
    assert nb.stage == "report"
    assert nb.output_format == "html"
    assert nb.content is not None
    assert "report" in base64.b64decode(nb.content).decode()
    # A declared notebook keeps its metadata, and with no HTML export falls
    # back to the raw notebook
    nb = app.projects.get_notebook_from_repo(
        project=project, repo=repo, path="notebooks/declared.ipynb"
    )
    assert nb.title == "Declared notebook"
    assert nb.stage is None
    assert nb.output_format == "notebook"
    # An undeclared notebook with no stage still resolves
    nb = app.projects.get_notebook_from_repo(
        project=project, repo=repo, path="notebooks/raw.ipynb"
    )
    assert nb.output_format == "notebook"
    # A path that doesn't exist is a 404
    with pytest.raises(HTTPException) as exc_info:
        app.projects.get_notebook_from_repo(
            project=project, repo=repo, path="notebooks/nope.ipynb"
        )
    assert exc_info.value.status_code == 404


def test_read_app_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        app.projects, "get_data_fpath_for_md5", lambda **kwargs: None
    )
    project = _make_project()
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    (repo_dir / "app").mkdir()
    (repo_dir / "app" / "index.html").write_text("<h1>app</h1>")
    (repo_dir / "app" / "assets").mkdir()
    (repo_dir / "app" / "assets" / "main.js").write_text("export default 1")
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Add app"])
    # A secret next to the checkout, i.e., what a traversal would reach
    (tmp_path / "secret.txt").write_text("password")
    read = app.projects.read_app_file
    assert (
        read(project=project, repo=repo, dir_path="app", rel_path="index.html")
        == b"<h1>app</h1>"
    )
    assert (
        read(
            project=project,
            repo=repo,
            dir_path="app",
            rel_path="assets/main.js",
        )
        == b"export default 1"
    )
    # Paths are normalized rather than passed through, so a request that
    # walks back into the app's own directory still resolves
    assert (
        read(
            project=project,
            repo=repo,
            dir_path="app",
            rel_path="assets/../index.html",
        )
        == b"<h1>app</h1>"
    )
    # Neither the declared app directory nor the requested path may leave the
    # repo. dir_path comes from the project's own calkit.yaml, and reads go
    # through the checkout directly, so an unchecked '..' would hand back any
    # file on the server.
    for dir_path, rel_path in [
        ("app", "../../secret.txt"),
        ("app", "/etc/passwd"),
        ("../", "secret.txt"),
        ("app/../..", "secret.txt"),
        ("/etc", "passwd"),
        ("app", ""),
    ]:
        assert (
            read(
                project=project,
                repo=repo,
                dir_path=dir_path,
                rel_path=rel_path,
            )
            is None
        ), (dir_path, rel_path)
    # A symlink out of the tree reads whatever it points at, so it's refused
    # the same way it is when browsing files
    (repo_dir / "app" / "leak.html").symlink_to(tmp_path / "secret.txt")
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Add symlink"])
    assert (
        read(project=project, repo=repo, dir_path="app", rel_path="leak.html")
        is None
    )


def test_get_notebook_from_repo_marimo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    project = _make_project()
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    (repo_dir / "calkit.yaml").write_text(
        "pipeline:\n"
        "  stages:\n"
        "    build-app:\n"
        "      kind: marimo\n"
        "      environment: py\n"
        "      notebook_path: notebook.py\n"
        "      output_path: app\n"
        "apps:\n"
        "  explorer:\n"
        "    kind: static-html\n"
        "    path: app/index.html\n"
        "    stage: build-app\n"
    )
    (repo_dir / "notebook.py").write_text(
        'import marimo\n__generated_with = "0.19.4"\napp = marimo.App()\n'
    )
    # A plain script that mentions marimo is not a notebook to show source for
    (repo_dir / "helper.py").write_text("# helpers for marimo\nx = 1\n")
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Add marimo notebook"])
    nb = app.projects.get_notebook_from_repo(
        project=project, repo=repo, path="notebook.py"
    )
    # The stage runs the notebook, so it links even though its kind isn't
    # jupyter-notebook
    assert nb.stage == "build-app"
    # That stage builds an app, so the notebook points at it
    assert nb.app == "explorer"
    # There's no executed copy of a marimo notebook to render, so its source
    # is what gets shown
    assert nb.output_format == "source"
    assert nb.content is not None
    assert "marimo.App()" in base64.b64decode(nb.content).decode()
    nb = app.projects.get_notebook_from_repo(
        project=project, repo=repo, path="helper.py"
    )
    assert nb.output_format != "source"
    assert nb.stage is None
    assert nb.app is None


def test_link_notebook_to_stage_and_app() -> None:
    ck_info = {
        "pipeline": {
            "stages": {
                "report": {
                    "kind": "jupyter-notebook",
                    "notebook_path": "notebooks/report.ipynb",
                },
                "build-app": {
                    "kind": "marimo",
                    "notebook_path": "notebook.py",
                },
                "simulate": {"kind": "python-script", "script_path": "run.py"},
            }
        },
        "apps": {"explorer": {"path": "app/index.html", "stage": "build-app"}},
    }
    # A marimo stage ties to its notebook the same way a jupyter-notebook
    # stage does, and that stage builds an app
    nb: dict = {"path": "notebook.py"}
    app.projects.link_notebook_to_stage_and_app(nb, ck_info)
    assert nb["stage"] == "build-app"
    assert nb["app"] == "explorer"
    # A stage that produces no app leaves the notebook without one
    nb = {"path": "notebooks/report.ipynb"}
    app.projects.link_notebook_to_stage_and_app(nb, ck_info)
    assert nb["stage"] == "report"
    assert "app" not in nb
    # A notebook no stage runs stays unlinked, and a script isn't a notebook
    for path in ["notebooks/orphan.ipynb", "run.py"]:
        nb = {"path": path}
        app.projects.link_notebook_to_stage_and_app(nb, ck_info)
        assert nb == {"path": path}
    # A stage declared in calkit.yaml wins nothing over one already set
    nb = {"path": "notebook.py", "stage": "hand-written"}
    app.projects.link_notebook_to_stage_and_app(nb, ck_info)
    assert nb["stage"] == "hand-written"
    # Nothing blows up on a project with no pipeline or apps
    nb = {"path": "notebook.py"}
    app.projects.link_notebook_to_stage_and_app(nb, {})
    assert nb == {"path": "notebook.py"}


def test_notebooks_from_ck_info() -> None:
    # The shape petebachant/nacafoil-openfoam uses: a marimo notebook that
    # only the pipeline names, with no `notebooks` section at all
    ck_info = {
        "pipeline": {
            "stages": {
                "plot-clcd": {
                    "kind": "python-script",
                    "script_path": "scripts/plot-clcd.py",
                },
                "app": {
                    "kind": "marimo-html-wasm",
                    "notebook_path": "notebook.py",
                    "output_dir": "app",
                },
            }
        }
    }
    assert app.projects.notebooks_from_ck_info(ck_info) == [
        {"path": "notebook.py"}
    ]
    # A declared notebook keeps its metadata rather than being duplicated by
    # the stage that runs it
    ck_info["notebooks"] = [
        {"path": "notebook.py", "title": "NACA 0012 explorer"},
        {"path": "notebooks/scratch.ipynb"},
    ]
    assert app.projects.notebooks_from_ck_info(ck_info) == [
        {"path": "notebook.py", "title": "NACA 0012 explorer"},
        {"path": "notebooks/scratch.ipynb"},
    ]
    # A project with nothing to list, and malformed entries, come back empty
    # rather than raising
    assert app.projects.notebooks_from_ck_info({}) == []
    assert app.projects.notebooks_from_ck_info({"notebooks": "nope"}) == []
    assert (
        app.projects.notebooks_from_ck_info(
            {"notebooks": [None, {"title": "No path"}]}
        )
        == []
    )


def test_find_notebook_paths_in_tree(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    (repo_dir / "top.ipynb").write_text("{}")
    (repo_dir / "notebooks").mkdir()
    (repo_dir / "notebooks" / "nested.ipynb").write_text("{}")
    (repo_dir / "notebooks" / "notes.md").write_text("hi")
    # Hidden directories hold cleaned/executed copies and virtualenvs, none
    # of which are the project's own notebooks
    (repo_dir / ".ipynb_checkpoints").mkdir()
    (repo_dir / ".ipynb_checkpoints" / "top-checkpoint.ipynb").write_text("{}")
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Add notebooks"])
    main_sha = repo.head.commit.hexsha
    tree = app.projects.get_repo_tree_for_ref(repo, None)
    assert app.projects.find_notebook_paths_in_tree(tree) == [
        "notebooks/nested.ipynb",
        "top.ipynb",
    ]
    # A notebook added on another branch belongs to that ref only, and the
    # working tree is whatever branch the cached clone sits on
    repo.git.checkout(["-b", "other"])
    (repo_dir / "later.ipynb").write_text("{}")
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Add later notebook"])
    other_sha = repo.head.commit.hexsha
    assert app.projects.find_notebook_paths_in_tree(
        app.projects.get_repo_tree_for_ref(repo, other_sha)
    ) == ["later.ipynb", "notebooks/nested.ipynb", "top.ipynb"]
    # The earlier ref doesn't see it, even though the checkout now does
    assert app.projects.find_notebook_paths_in_tree(
        app.projects.get_repo_tree_for_ref(repo, main_sha)
    ) == ["notebooks/nested.ipynb", "top.ipynb"]
    # A symlinked directory pointing back up the tree doesn't hang the walk
    (repo_dir / "loop").symlink_to(repo_dir)
    assert "loop" not in str(
        app.projects.find_notebook_paths_in_tree(
            app.projects.get_repo_tree_for_ref(repo, None)
        )
    )


def test_drop_stale_lock_stages() -> None:
    from app.projects import drop_stale_lock_stages

    lock = {
        "schema": "2.0",
        "stages": {
            "baseline-nsys": {"outs": [{"path": "r/b.sqlite", "md5": "live"}]},
            "baseline-nsys-to-sqlite": {
                "outs": [{"path": "r/b.sqlite", "md5": "stale"}]
            },
            "plot@0": {"outs": [{"path": "f/0.png", "md5": "a"}]},
            "plot@1": {"outs": [{"path": "f/1.png", "md5": "b"}]},
            "gone@0": {"outs": [{"path": "f/x.png", "md5": "c"}]},
        },
    }
    dvc_yaml = {"stages": {"baseline-nsys": {}, "plot": {"foreach": [0, 1]}}}
    pruned = drop_stale_lock_stages(lock, dvc_yaml)
    # Live stages stay, foreach instances count under their base name, and
    # the renamed stage's leftover entry is gone, so the path resolves to
    # the live hash
    assert set(pruned["stages"]) == {"baseline-nsys", "plot@0", "plot@1"}
    assert pruned["schema"] == "2.0"
    # Nothing to prune returns the same object; odd inputs pass through
    assert drop_stale_lock_stages(pruned, dvc_yaml) is pruned
    assert drop_stale_lock_stages(lock, {}) is lock
    assert drop_stale_lock_stages({}, dvc_yaml) == {}
