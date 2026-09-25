"""Tests for app.index."""

import uuid

from sqlmodel import Session

import app.index
from app import users
from app.models import Project, Question, UserCreate


def test_extract_question_text() -> None:
    extract = app.index.extract_question_text
    assert extract("Plain question?") == "Plain question?"
    assert extract({"question": "Rich?", "hypothesis": "h"}) == "Rich?"
    assert extract({}) == ""
    # A non-string/non-dict value (e.g. a list) yields empty text, not a repr.
    assert extract(["a", "b"]) == ""  # type: ignore


def _make_project(db: Session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    owner = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"idx-{suffix}@example.com",
            password="indexpassword123",
            account_name=f"idx{suffix}",
            github_username=f"idx{suffix}",
        ),
    )
    project = Project(
        name=f"idx-{suffix}",
        title="Index Test",
        git_repo_url=f"https://github.com/idx{suffix}/idx-{suffix}",
        owner_account_id=owner.account.id,
        owner_account=owner.account,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def test_index_questions(db: Session) -> None:
    # The index follows calkit.yaml: added, reworded, reordered and removed
    # questions all end up reflected, and a row keeps its id while its text
    # is edited so anything pointing at it survives a rewording.
    project = _make_project(db)
    try:
        assert app.index.index_questions(db, project, {}) == 0
        assert list(project.questions) == []
        n = app.index.index_questions(
            db,
            project,
            {
                "questions": [
                    "Does it work?",
                    {"question": "How well?", "hypothesis": "Very"},
                    "And for how long?",
                ]
            },
        )
        assert n == 3
        rows = sorted(project.questions, key=lambda q: q.number)
        assert [q.number for q in rows] == [1, 2, 3]
        # A mapping is indexed by its text, not its whole body
        assert [q.question for q in rows] == [
            "Does it work?",
            "How well?",
            "And for how long?",
        ]
        first_id = rows[0].id
        # Rewording reuses the row at that number rather than replacing it
        app.index.index_questions(
            db, project, {"questions": ["Does it really work?", "How well?"]}
        )
        rows = sorted(project.questions, key=lambda q: q.number)
        assert [q.question for q in rows] == [
            "Does it really work?",
            "How well?",
        ]
        assert rows[0].id == first_id
        # The third is gone from the file, so it goes from the index too
        assert len(rows) == 2
        assert db.get(Question, first_id) is not None
        # Emptying the file empties the index
        assert app.index.index_questions(db, project, {"questions": []}) == 0
        assert list(project.questions) == []
    finally:
        for q in list(project.questions):
            db.delete(q)
        db.delete(project)
        db.commit()


def test_index_project_covers_every_indexed_artifact(db: Session) -> None:
    # index_project is what the warm job calls; it should report what it
    # indexed so adding an artifact shows up in the warm log.
    project = _make_project(db)
    try:
        counts = app.index.index_project(
            db, project, {"questions": ["Does it work?"]}
        )
        assert counts == {"questions": 1}
    finally:
        for q in list(project.questions):
            db.delete(q)
        db.delete(project)
        db.commit()
