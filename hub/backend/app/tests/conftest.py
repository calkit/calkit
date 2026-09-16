import os
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
def isolate_git_config(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[None, None, None]:
    """Keep the suite's git config out of whoever is running it.

    Tests shell out to git and to `calkit`, which commits and so needs an
    identity. Writing that identity with `git config --global` lands in the
    developer's own ~/.gitconfig when the suite runs outside a container, and
    silently reauthors their next commit. Point git's global config at a
    throwaway file instead, so those writes have somewhere harmless to go.
    """
    config_path = tmp_path_factory.mktemp("gitconfig") / "config"
    config_path.write_text(
        "[user]\n\tname = CI Test\n\temail = ci-test@example.com\n"
    )
    old = os.environ.get("GIT_CONFIG_GLOBAL")
    os.environ["GIT_CONFIG_GLOBAL"] = str(config_path)
    yield
    if old is None:
        del os.environ["GIT_CONFIG_GLOBAL"]
    else:
        os.environ["GIT_CONFIG_GLOBAL"] = old


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
