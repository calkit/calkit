import uuid
from datetime import timedelta
from unittest.mock import patch

import git
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import users
from app.api.routes.projects.dvc import record_dvc_push
from app.config import settings
from app.core import utcnow
from app.models import (
    ProjectComment,
    ProjectDvcPush,
    Release,
    UserCreate,
    UserProjectAccess,
)
from app.models.core import ROLE_IDS
from app.tests.api.routes.projects.test_overleaf_links import (
    _make_owner_with_project,
)


def test_get_project_activity(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner = project.owner_account.user
    assert owner is not None
    url = (
        f"{settings.API_V1_STR}/projects/{project.owner_account_name}/"
        f"{project.name}/activity"
    )
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Committer")
        cw.set_value("user", "email", "c@example.com")
    (tmp_path / "repo" / "a.txt").write_text("a\n")
    repo.git.add(all=True)
    repo.git.commit("-m", "First commit")
    (tmp_path / "repo" / "b.txt").write_text("b\n")
    repo.git.add(all=True)
    repo.git.commit("-m", "Second commit\n\nWith a body")
    now = utcnow()
    # A collaborator added a day ago, a comment an hour ago, a reply just
    # now, a release a week ago, a GitHub-derived access row (no time of
    # its own) and two bursts of DVC pushes
    suffix = uuid.uuid4().hex[:8]
    collaborator = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"collab-{suffix}@example.com",
            password="testpassword123",
            account_name=f"collab{suffix}",
            full_name="Colla Borator",
        ),
    )
    cached = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"cached-{suffix}@example.com",
            password="testpassword123",
            account_name=f"cached{suffix}",
        ),
    )
    db.add(
        UserProjectAccess(
            project_id=project.id,
            user_id=collaborator.id,
            role_id=ROLE_IDS["write"],
            created=now - timedelta(days=1),
        )
    )
    db.add(
        UserProjectAccess(
            project_id=project.id,
            user_id=cached.id,
            github_access="read",
            created=now - timedelta(minutes=5),
        )
    )
    top = ProjectComment(
        project_id=project.id,
        user_id=owner.id,
        comment="Looks good",
        artifact_path="figures/plot.png",
        artifact_type="figure",
        created=now - timedelta(hours=1),
    )
    db.add(top)
    db.commit()
    db.add(
        ProjectComment(
            project_id=project.id,
            user_id=collaborator.id,
            comment="Thanks",
            parent_id=top.id,
            created=now,
        )
    )
    db.add(
        Release(
            project_id=project.id,
            name="v1.0.0",
            created_by_user_id=owner.id,
            created=now - timedelta(days=7),
        )
    )
    db.commit()
    record_dvc_push(session=db, project_id=project.id, user=owner)
    record_dvc_push(session=db, project_id=project.id, user=owner)
    pushes = db.exec(
        select(ProjectDvcPush).where(ProjectDvcPush.project_id == project.id)
    ).all()
    # Two uploads in quick succession are one push of two files
    assert len(pushes) == 1
    assert pushes[0].n_files == 2
    pushes[0].updated = now - timedelta(days=2)
    pushes[0].created = now - timedelta(days=2)
    db.add(pushes[0])
    db.commit()
    record_dvc_push(session=db, project_id=project.id, user=collaborator)
    with patch("app.api.routes.projects.activity.get_repo", return_value=repo):
        r = client.get(url, headers=headers)
        assert r.status_code == 200, r.text
        items = r.json()
        kinds = [i["kind"] for i in items]
        # Newest first (the commits predate ``now``), every source
        # represented, the cached GitHub access row left out
        assert kinds == [
            "dvc-push",
            "comment",
            "commit",
            "commit",
            "comment",
            "collaborator",
            "dvc-push",
            "release",
        ]
        assert [i["timestamp"] for i in items] == sorted(
            (i["timestamp"] for i in items), reverse=True
        )
        (
            latest_push,
            reply,
            newest,
            oldest,
            comment,
            collab,
            older_push,
            release,
        ) = items
        assert newest["title"] == "Second commit"
        assert newest["actor"] == "Committer"
        assert newest["id"] == repo.head.commit.hexsha
        assert newest["link"] == f"history?commit={repo.head.commit.hexsha}"
        assert oldest["title"] == "First commit"
        assert reply["title"] == "Replied on the project"
        assert reply["actor"] == "Colla Borator"
        assert reply["link"] is None
        assert latest_push["title"] == "Pushed 1 file to DVC storage"
        assert latest_push["actor"] == "Colla Borator"
        assert latest_push["link"] == "files"
        assert comment["title"] == "Commented on figures/plot.png"
        assert comment["id"] == str(top.id)
        assert comment["link"] == "figures?path=figures%2Fplot.png"
        assert collab["title"] == "Colla Borator joined as write"
        assert collab["link"] == "collaborators"
        assert older_push["title"] == "Pushed 2 files to DVC storage"
        assert older_push["actor"] == project.owner_account_name
        assert release["title"] == "Released v1.0.0"
        assert release["link"] == "releases"
        # The limit cuts the merged list, not any one source
        r = client.get(url, params={"limit": 3}, headers=headers)
        assert [i["kind"] for i in r.json()] == [
            "dvc-push",
            "comment",
            "commit",
        ]
        # A private project's activity isn't for strangers
        r = client.get(url)
        assert r.status_code in (401, 403)
