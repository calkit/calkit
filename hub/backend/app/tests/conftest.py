from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import settings
from app.db import engine, init_db
from app.main import app
from app.tests import (
    authentication_token_from_email,
    get_superuser_token_headers,
)


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        init_db(session)
        yield session


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="session")
def normal_user_token_headers(
    client: TestClient, db: Session
) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
