"""Tests for ``app.users``."""

from unittest import mock

import pytest
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlmodel import Session

from app import users
from app.config import settings
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


def test_create_user_reserved_account_names(db: Session) -> None:
    # Route segments and product vocabulary can't be account names, in any
    # casing, since account names live at the URL root
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
