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
    for name in [
        "hub",
        "cloud",
        "calkit",
        "Hub",
        "CLOUD",
        "settings",
        "compute",
        "machines",
        "workspaces",
    ]:
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


def test_get_huggingface_token(db: Session) -> None:
    user = users.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=random_lower_string()
        ),
    )

    def save(access_token: str, expires_in_minutes: int) -> None:
        users.save_external_credential(
            session=db,
            user=user,
            provider="huggingface",
            secret_payload=json.dumps(
                {"access_token": access_token, "refresh_token": "hf_refresh"}
            ),
            expires=utcnow() + timedelta(minutes=expires_in_minutes),
        )

    # One with plenty of life left isn't refreshed
    save("hf_current", 60)
    with mock.patch.object(users.requests, "post") as post:
        assert users.get_huggingface_token(db, user) == "hf_current"
        post.assert_not_called()
    # One about to expire is
    save("hf_current", 1)
    userinfo = SimpleNamespace(
        ok=True, json=lambda: {"preferred_username": "someone", "orgs": []}
    )
    with (
        mock.patch.object(
            users.requests,
            "post",
            return_value=SimpleNamespace(
                status_code=200,
                json=lambda: {"access_token": "hf_new", "expires_in": 3600},
            ),
        ) as post,
        mock.patch.object(users.requests, "get", return_value=userinfo),
    ):
        assert users.get_huggingface_token(db, user) == "hf_new"
        assert post.call_count == 1
    # One another request refreshed while this one waited for the lock isn't
    # refreshed again
    save("hf_current", 1)
    get_credential = users.get_external_credential

    def get_then_refresh_elsewhere(**kwargs):
        credential = get_credential(**kwargs)
        with Session(db.get_bind()) as other:
            row = other.get(type(credential), credential.id)
            row.secret_payload = users.encrypt_secret(
                json.dumps({"access_token": "hf_other"})
            )
            row.expires = utcnow() + timedelta(hours=1)
            other.add(row)
            other.commit()
        return credential

    with (
        mock.patch.object(
            users,
            "get_external_credential",
            side_effect=get_then_refresh_elsewhere,
        ),
        mock.patch.object(users.requests, "post") as post,
    ):
        assert users.get_huggingface_token(db, user) == "hf_other"
        post.assert_not_called()
    # An outage doesn't disconnect the account
    save("hf_current", 1)
    for post_kwargs in (
        {"side_effect": users.requests.ConnectionError("down")},
        {"return_value": SimpleNamespace(status_code=500, text="down")},
    ):
        with (
            mock.patch.object(users.requests, "post", **post_kwargs),
            pytest.raises(HTTPException) as e,
        ):
            users.get_huggingface_token(db, user)
        assert e.value.status_code == 503
        assert (
            users.get_external_credential(
                session=db, user=user, provider="huggingface"
            )
            is not None
        )
    # Nor does failing to get account details while refreshing
    with (
        mock.patch.object(
            users.requests,
            "post",
            return_value=SimpleNamespace(
                status_code=200,
                json=lambda: {"access_token": "hf_new", "expires_in": 3600},
            ),
        ),
        mock.patch.object(
            users.requests,
            "get",
            side_effect=users.requests.ConnectionError("down"),
        ),
    ):
        assert users.get_huggingface_token(db, user) == "hf_new"
    # A rejected refresh disconnects the account
    save("hf_current", 1)
    with (
        mock.patch.object(
            users.requests,
            "post",
            return_value=SimpleNamespace(status_code=400, text="bad"),
        ),
        pytest.raises(HTTPException) as e,
    ):
        users.get_huggingface_token(db, user)
    assert e.value.status_code == 401
    assert (
        users.get_external_credential(
            session=db, user=user, provider="huggingface"
        )
        is None
    )


def test_get_box_token(db: Session) -> None:
    from app.models import UserExternalCredential

    user = users.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=random_lower_string()
        ),
    )

    def save(access_token: str, expires_in_minutes: int, idle_days: int = 0):
        credential = users.save_external_credential(
            session=db,
            user=user,
            provider="box",
            secret_payload=json.dumps(
                {"access_token": access_token, "refresh_token": "refresh_1"}
            ),
            provider_account_id="42",
            metadata_json={"login": "someone@example.edu"},
            expires=utcnow() + timedelta(minutes=expires_in_minutes),
            refresh_token_expires=utcnow()
            + users.BOX_REFRESH_TOKEN_LIFETIME
            - timedelta(days=idle_days),
        )
        return credential

    def get_tokens() -> dict:
        credential = users.get_external_credential(
            session=db, user=user, provider="box"
        )
        assert credential is not None
        return dict(
            json.loads(users.decrypt_secret(credential.secret_payload))
        )

    refreshed = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "access_token": "new",
            "refresh_token": "refresh_2",
            "expires_in": 3600,
        },
    )
    me = SimpleNamespace(
        ok=True,
        json=lambda: {
            "id": "42",
            "login": "someone@example.edu",
            "name": "Someone",
            "enterprise": {"name": "Some University"},
        },
    )
    # One with plenty of life left isn't refreshed, unless forced
    save("current", 60)
    with mock.patch.object(users.requests, "post") as post:
        assert users.get_box_token(db, user) == "current"
        post.assert_not_called()
    with (
        mock.patch.object(
            users.requests, "post", return_value=refreshed
        ) as post,
        mock.patch.object(users.requests, "get", return_value=me),
    ):
        assert users.get_box_token(db, user, force=True) == "new"
    # Each refresh token works once, so the new one replaces it, and the
    # connection's life starts over
    assert post.call_args.kwargs["data"]["refresh_token"] == "refresh_1"
    assert get_tokens()["refresh_token"] == "refresh_2"
    credential = users.get_external_credential(
        session=db, user=user, provider="box"
    )
    assert credential is not None and credential.refresh_token_expires
    assert credential.refresh_token_expires > utcnow() + timedelta(days=59)
    assert credential.metadata_json == {
        "login": "someone@example.edu",
        "name": "Someone",
        "enterprise": "Some University",
    }
    # Neither an outage nor the hub's own client credentials being wrong
    # disconnect the account
    save("current", 1)
    for status, error in ((500, None), (400, "invalid_client")):
        with (
            mock.patch.object(
                users.requests,
                "post",
                return_value=SimpleNamespace(
                    status_code=status, text="", json=lambda: {"error": error}
                ),
            ),
            pytest.raises(HTTPException) as e,
        ):
            users.get_box_token(db, user)
        assert e.value.status_code == 503
        assert get_tokens()["access_token"] == "current"
    # A spent or expired refresh token does, but which Box account it was is
    # kept, so storage in it can't be taken over by another
    with (
        mock.patch.object(
            users.requests,
            "post",
            return_value=SimpleNamespace(
                status_code=400,
                text="",
                json=lambda: {"error": "invalid_grant"},
            ),
        ),
        pytest.raises(HTTPException) as e,
    ):
        users.get_box_token(db, user)
    assert e.value.status_code == 401
    assert get_tokens() == {}
    credential = users.get_external_credential(
        session=db, user=user, provider="box"
    )
    assert credential is not None and credential.provider_account_id == "42"
    with (
        mock.patch.object(users.requests, "post") as post,
        pytest.raises(HTTPException) as e,
    ):
        users.get_box_token(db, user)
    assert e.value.status_code == 401
    post.assert_not_called()
    # The daily job refreshes only connections unused for a month, then
    # queues itself for the next day
    save("current", 60, idle_days=31)
    other = users.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=random_lower_string()
        ),
    )
    users.save_external_credential(
        session=db,
        user=other,
        provider="box",
        secret_payload=json.dumps(
            {"access_token": "other", "refresh_token": "other_refresh"}
        ),
        expires=utcnow() + timedelta(hours=1),
        refresh_token_expires=utcnow() + timedelta(days=59),
    )
    from sqlmodel import col, select

    idle_ids = {
        c.user_id
        for c in db.exec(
            select(UserExternalCredential).where(
                UserExternalCredential.provider == "box",
                col(UserExternalCredential.refresh_token_expires)
                < utcnow() + timedelta(days=30),
            )
        ).all()
    }
    with (
        mock.patch.object(
            users.requests, "post", return_value=refreshed
        ) as post,
        mock.patch.object(users.requests, "get", return_value=me),
    ):
        assert users.refresh_idle_box_tokens() == len(idle_ids)
    refreshed_tokens = {
        c.kwargs["data"]["refresh_token"] for c in post.call_args_list
    }
    assert "refresh_1" in refreshed_tokens
    assert "other_refresh" not in refreshed_tokens
    db.expire_all()
    assert get_tokens()["refresh_token"] == "refresh_2"
