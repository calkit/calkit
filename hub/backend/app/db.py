"""Database-related functionality."""

import logging

from app import users
from app.config import settings
from app.models import User, UserCreate
from sqlalchemy import Engine
from sqlmodel import Session, create_engine, select
from tenacity import (
    after_log,
    before_log,
    retry,
    stop_after_attempt,
    wait_fixed,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5  # 5 minutes
wait_seconds = 1

# Each worker process gets its own pool, so keep per-process limits modest:
# with 12 workers (8 backend + 4 backend-dvc), 5 + 5 = 10 per process gives a
# 120-connection worst case, comfortably under the db's max_connections (300).
engine = create_engine(
    str(settings.SQLALCHEMY_DATABASE_URI), pool_size=5, max_overflow=5
)

# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more details: https://github.com/fastapi/full-stack-fastapi-template/issues/28


def init_db(session: Session) -> None:
    # Tables should be created with Alembic migrations
    # But if you don't want to use migrations, create
    # the tables un-commenting the next lines
    # from sqlmodel import SQLModel

    # from app.core.engine import engine
    # This works because the models are already imported and registered from app.models
    # SQLModel.metadata.create_all(engine)

    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            github_username=settings.FIRST_SUPERUSER_GITHUB_USERNAME,
            is_superuser=True,
        )
        user = users.create_user(session=session, user_create=user_in)


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
def pre_start(db_engine: Engine) -> None:
    try:
        with Session(db_engine) as session:
            # Try to create session to check if DB is awake
            session.exec(select(1))
    except Exception as e:
        logger.error(e)
        raise e


def make_session() -> Session:
    return Session(engine)
