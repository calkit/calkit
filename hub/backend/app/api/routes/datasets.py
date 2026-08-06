"""API endpoints for datasets."""

import logging

import sqlalchemy
from app.api.deps import CurrentUserOptional, SessionDep
from app.models import Dataset, Project, ProjectPublic
from fastapi import APIRouter
from sqlmodel import SQLModel, func, or_, select, and_

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


class DatasetResponse(SQLModel):
    project: ProjectPublic
    path: str
    title: str | None
    description: str | None
    imported_from: str | None


class DatasetsResponse(SQLModel):
    data: list[DatasetResponse]
    count: int


@router.get("/datasets")
def get_datasets(
    session: SessionDep,
    current_user: CurrentUserOptional,
    limit: int = 100,
    offset: int = 0,
    include_imported: bool = False,
    search_for: str | None = None,
) -> DatasetsResponse:
    # TODO: Handle collaborator access for private project datasets
    if current_user is None:
        where_clause = Project.is_public
    else:
        where_clause = or_(
            Project.is_public,
            Project.owner_account_id == current_user.account.id,
        )
    if search_for is not None:
        search_for = f"%{search_for}%"
        where_clause = and_(
            where_clause,
            or_(
                Dataset.path.ilike(search_for),
                Dataset.title.ilike(search_for),
                Dataset.description.ilike(search_for),
                Project.name.ilike(search_for),
                Project.title.ilike(search_for),
                Project.description.ilike(search_for),
            ),
        )
    count_query = (
        select(func.count())
        .select_from(Dataset)
        .join(Project)
        .where(where_clause)
    )
    if not include_imported:
        count_query = count_query.filter(Dataset.imported_from.is_(None))
    count = session.exec(count_query).one()
    select_query = (
        select(Dataset)
        .join(Project)
        .where(where_clause)
        .order_by(sqlalchemy.asc(Project.title))
        .limit(limit)
        .offset(offset)
    )
    if not include_imported:
        select_query = select_query.filter(Dataset.imported_from.is_(None))
    datasets = session.exec(select_query).all()
    return DatasetsResponse(data=datasets, count=count)
