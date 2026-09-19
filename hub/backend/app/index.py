"""Indexing a project's artifacts so they can be found across the hub.

Git is the record. These rows are a view of it, kept so that one query can
answer a question about every project at once -- which questions are being
asked, which environments already exist and could be reused -- without
opening every clone.

Because it is a view and not the record, nothing a project's own pages show
is allowed to depend on it being current: those read ``calkit.yaml`` at the
commit they are showing. The index is rebuilt by the warm job after a push,
so it lags by however long that takes, and writes made through the hub
update it as they go.

Adding an artifact means writing an ``index_*`` function here and listing it
in ``index_project``; the warm job picks it up without further wiring.
"""

from __future__ import annotations

from copy import deepcopy

from sqlmodel import Session

from app.core import logger
from app.models import Project, Question


def index_project(
    session: Session, project: Project, ck_info: dict
) -> dict[str, int]:
    """Bring every indexed artifact of *project* in line with calkit.yaml.

    Returns how many of each are indexed, for the warm job's log.
    """
    return {"questions": index_questions(session, project, ck_info)}


def index_questions(session: Session, project: Project, ck_info: dict) -> int:
    """Index the project's research questions, by position.

    A question has no identifier of its own in ``calkit.yaml`` -- it is the
    nth entry in a list -- so the row for number n is reused and rewritten
    rather than deleted and recreated. That keeps its id stable while the
    text is edited, which is what lets anything referring to a question by
    id survive a rewording.
    """
    questions_ck = list(ck_info.get("questions") or [])
    incoming = deepcopy(questions_ck)
    existing = sorted(project.questions, key=lambda q: q.number)
    for n, existing_q in enumerate(existing[: len(incoming)]):
        existing_q.question = extract_question_text(incoming[n])
        existing_q.number = n + 1
    for n, new in enumerate(incoming[len(existing) :], start=len(existing)):
        project.questions.append(
            Question(
                project_id=project.id,
                number=n + 1,
                question=extract_question_text(new),
            )
        )
    for extra in existing[len(incoming) :]:
        project.questions.remove(extra)
        session.delete(extra)
    if session.dirty or session.new or session.deleted:
        session.commit()
        session.refresh(project)
    logger.info(f"Indexed {len(questions_ck)} questions for {project.name}")
    return len(questions_ck)


def extract_question_text(question: str | dict) -> str:
    """Extract the question text from a calkit.yaml question entry.

    A question may be a plain string or an object with a ``question`` field.
    Any other/unexpected type (e.g. a list) yields an empty string rather than
    a coerced repr, so a non-string never reaches the DB model's ``question``
    field (and the empty text signals to the user that something is off).
    """
    if isinstance(question, dict):
        value = question.get("question", "")
    else:
        value = question
    return value if isinstance(value, str) else ""
