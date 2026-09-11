"""Tests for ``app.users``."""

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlmodel import Session

from app import users, utcnow
from app.config import settings
from app.core import (
    INVALID_ACCOUNT_NAMES,
    ORG_ONLY_ACCOUNT_NAMES,
)
from app.models import User, UserCreate, UserUpdate
from app.security import verify_password
from app.tests import random_email, random_lower_string


def test_create_user(db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password)
    user = users.create_user(session=db, user_create=user_in)
    assert user.email == email
    assert hasattr(user, "hashed_password")


def test_create_user_email_allowlist(db: Session) -> None:
    # An empty allowlist (the default) lets anyone in
    email = random_email()
    user_in = UserCreate(email=email, password=random_lower_string())
    assert users.create_user(session=db, user_create=user_in).email == email
    # With one set, only listed emails can be created, case-insensitively
    allowed, denied = random_email(), random_email()
    with mock.patch.object(settings, "ALLOWED_USER_EMAILS", [allowed.upper()]):
        user_in = UserCreate(email=allowed, password=random_lower_string())
        assert (
            users.create_user(session=db, user_create=user_in).email == allowed
        )
        user_in = UserCreate(email=denied, password=random_lower_string())
        with pytest.raises(HTTPException) as exc_info:
            users.create_user(session=db, user_create=user_in)
        assert exc_info.value.status_code == 403
        # The bootstrap superuser is exempt: prestart recreates it on every
        # deploy, so an allowlist omitting it would fail the deploy
        users.check_email_allowed(settings.FIRST_SUPERUSER)


def test_create_user_reserved_account_names(db: Session) -> None:
    # Route segments can't be account names, in any casing, since account
    # names live at the URL root. 'calkit' is reserved from users too, but
    # only so it stays available as an org (see ORG_ONLY_ACCOUNT_NAMES),
    # which org creation still permits.
    assert "calkit" not in INVALID_ACCOUNT_NAMES
    assert "calkit" in ORG_ONLY_ACCOUNT_NAMES
    for name in ["hub", "cloud", "calkit", "Hub", "CLOUD", "settings"]:
        user_in = UserCreate(
            email=random_email(),
            password=random_lower_string(),
            account_name=name,
        )
        with pytest.raises(HTTPException) as exc_info:
            users.create_user(session=db, user_create=user_in)
        assert exc_info.value.status_code == 422


def test_authenticate_user(db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password)
    user = users.create_user(session=db, user_create=user_in)
    authenticated_user = users.authenticate(
        session=db, email=email, password=password
    )
    assert authenticated_user
    assert user.email == authenticated_user.email


def test_not_authenticate_user(db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    user = users.authenticate(session=db, email=email, password=password)
    assert user is None


def test_check_if_user_is_active(db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password)
    user = users.create_user(session=db, user_create=user_in)
    assert user.is_active is True


def test_check_if_user_is_active_inactive(db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password, is_active=False)
    user = users.create_user(session=db, user_create=user_in)
    assert user.is_active is False


def test_check_if_user_is_superuser(db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password, is_superuser=True)
    user = users.create_user(session=db, user_create=user_in)
    assert user.is_superuser is True


def test_check_if_user_is_superuser_normal_user(db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = users.create_user(session=db, user_create=user_in)
    assert user.is_superuser is False


def test_get_user(db: Session) -> None:
    password = random_lower_string()
    username = random_email()
    user_in = UserCreate(email=username, password=password, is_superuser=True)
    user = users.create_user(session=db, user_create=user_in)
    user_2 = db.get(User, user.id)
    assert user_2
    assert user.email == user_2.email
    assert jsonable_encoder(user) == jsonable_encoder(user_2)


def test_update_user(db: Session) -> None:
    password = random_lower_string()
    email = random_email()
    user_in = UserCreate(email=email, password=password, is_superuser=True)
    user = users.create_user(session=db, user_create=user_in)
    new_password = random_lower_string()
    user_in_update = UserUpdate(password=new_password, is_superuser=True)
    if user.id is not None:
        users.update_user(session=db, db_user=user, user_in=user_in_update)
    user_2 = db.get(User, user.id)
    assert user_2
    assert user.email == user_2.email
    assert verify_password(new_password, user_2.hashed_password)


def test_get_github_token_refreshes_only_when_due(db: Session) -> None:
    user = users.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=random_lower_string()
        ),
    )
    payload = json.dumps(
        {"access_token": "gho_current", "refresh_token": "ghr_current"}
    )
    # A credential with plenty of life left is returned straight from the
    # fast path, which reads without SELECT ... FOR UPDATE so concurrent
    # requests for this user don't serialize on the row.
    users.save_external_credential(
        session=db,
        user=user,
        provider="github",
        secret_payload=payload,
        expires=utcnow() + timedelta(hours=5),
        refresh_token_expires=utcnow() + timedelta(days=30),
    )
    with mock.patch.object(users.requests, "post") as post:
        assert users.get_github_token(db, user) == "gho_current"
        post.assert_not_called()
    # Inside the 30 minute refresh window it does go to GitHub, and the new
    # token is what comes back.
    users.save_external_credential(
        session=db,
        user=user,
        provider="github",
        secret_payload=payload,
        expires=utcnow() + timedelta(minutes=5),
        refresh_token_expires=utcnow() + timedelta(days=30),
    )
    refreshed = (
        "access_token=gho_new&refresh_token=ghr_new"
        "&expires_in=28800&refresh_token_expires_in=15811200"
    )
    with mock.patch.object(
        users.requests,
        "post",
        return_value=SimpleNamespace(status_code=200, text=refreshed),
    ) as post:
        assert users.get_github_token(db, user) == "gho_new"
        assert post.call_count == 1
    # Once refreshed, the next call is back on the lock-free fast path.
    with mock.patch.object(users.requests, "post") as post:
        assert users.get_github_token(db, user) == "gho_new"
        post.assert_not_called()
