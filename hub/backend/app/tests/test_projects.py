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
