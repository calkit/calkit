import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import users
from app.config import settings
from app.models import User, UserCreate
from app.security import verify_password
from app.tests import random_email, random_lower_string


def test_get_users_superuser_me(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get("/user", headers=superuser_token_headers)
    current_user = r.json()
    assert current_user
    assert current_user["is_active"] is True
    assert current_user["is_superuser"]
    assert current_user["email"] == settings.FIRST_SUPERUSER


def test_get_users_normal_user_me(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get("/user", headers=normal_user_token_headers)
    current_user = r.json()
    assert current_user
    assert current_user["is_active"] is True
    assert current_user["is_superuser"] is False
    assert current_user["email"] == settings.EMAIL_TEST_USER


def test_create_user_new_email(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    with (
        patch("app.messaging.send_email", return_value=None),
        patch("app.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.config.settings.SMTP_USER", "admin@example.com"),
    ):
        username = random_email()
        password = random_lower_string()
        data = {"email": username, "password": password}
        r = client.post(
            "/users",
            headers=superuser_token_headers,
            json=data,
        )
        assert 200 <= r.status_code < 300
        created_user = r.json()
        user = users.get_user_by_email(session=db, email=username)
        assert user
        assert user.email == created_user["email"]


def test_get_existing_user(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = users.create_user(session=db, user_create=user_in)
    user_id = user.id
    r = client.get(
        f"/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert 200 <= r.status_code < 300
    api_user = r.json()
    existing_user = users.get_user_by_email(session=db, email=username)
    assert existing_user
    assert existing_user.email == api_user["email"]


def test_get_existing_user_current_user(
    client: TestClient, db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = users.create_user(session=db, user_create=user_in)
    user_id = user.id
    login_data = {
        "username": username,
        "password": password,
    }
    r = client.post("/login/access-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}
    r = client.get(
        f"/users/{user_id}",
        headers=headers,
    )
    assert 200 <= r.status_code < 300
    api_user = r.json()
    existing_user = users.get_user_by_email(session=db, email=username)
    assert existing_user
    assert existing_user.email == api_user["email"]


def test_get_existing_user_permissions_error(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"/users/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 404


def test_create_user_existing_username(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    # username = email
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    users.create_user(session=db, user_create=user_in)
    data = {"email": username, "password": password}
    r = client.post(
        "/users",
        headers=superuser_token_headers,
        json=data,
    )
    created_user = r.json()
    assert r.status_code == 400
    assert "_id" not in created_user


def test_create_user_by_normal_user(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    username = random_email()
    password = random_lower_string()
    data = {"email": username, "password": password}
    r = client.post(
        "/users",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 403


def test_retrieve_users(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    users.create_user(session=db, user_create=user_in)
    username2 = random_email()
    password2 = random_lower_string()
    user_in2 = UserCreate(email=username2, password=password2)
    users.create_user(session=db, user_create=user_in2)
    r = client.get("/users/", headers=superuser_token_headers)
    all_users = r.json()
    assert len(all_users["data"]) > 1
    assert "count" in all_users
    for item in all_users["data"]:
        assert "email" in item


def test_update_user_me(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    full_name = "Updated Name"
    email = random_email()
    data = {"full_name": full_name, "email": email}
    r = client.patch(
        "/user",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 200
    updated_user = r.json()
    assert updated_user["email"] == email
    assert updated_user["full_name"] == full_name

    user_query = select(User).where(User.email == email)
    user_db = db.exec(user_query).first()
    assert user_db
    assert user_db.email == email
    assert user_db.full_name == full_name


def test_update_password_me(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    new_password = random_lower_string()
    data = {
        "current_password": settings.FIRST_SUPERUSER_PASSWORD,
        "new_password": new_password,
    }
    r = client.patch(
        "/user/password",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    updated_user = r.json()
    assert updated_user["message"] == "Password updated successfully"
    user_query = select(User).where(User.email == settings.FIRST_SUPERUSER)
    user_db = db.exec(user_query).first()
    assert user_db
    assert user_db.email == settings.FIRST_SUPERUSER
    assert verify_password(new_password, user_db.hashed_password)
    # Revert to the old password to keep consistency in test
    old_data = {
        "current_password": new_password,
        "new_password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.patch(
        "/user/password",
        headers=superuser_token_headers,
        json=old_data,
    )
    db.refresh(user_db)

    assert r.status_code == 200
    assert verify_password(
        settings.FIRST_SUPERUSER_PASSWORD, user_db.hashed_password
    )


def test_update_password_me_incorrect_password(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    new_password = random_lower_string()
    data = {"current_password": new_password, "new_password": new_password}
    r = client.patch(
        "/user/password",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    updated_user = r.json()
    assert updated_user["detail"] == "Incorrect password"


def test_update_user_me_email_exists(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = users.create_user(session=db, user_create=user_in)
    data = {"email": user.email}
    r = client.patch(
        "/user",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "User with this email already exists"


def test_update_password_me_same_password_error(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {
        "current_password": settings.FIRST_SUPERUSER_PASSWORD,
        "new_password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.patch(
        "/user/password",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    updated_user = r.json()
    assert (
        updated_user["detail"]
        == "New password cannot be the same as the current one"
    )


def test_register_user(client: TestClient, db: Session) -> None:
    """A user can self-register with email + password and no GitHub account."""
    email = random_email()
    password = random_lower_string()
    full_name = random_lower_string()
    data = {"email": email, "password": password, "full_name": full_name}
    r = client.post(
        "/users/signup",
        json=data,
    )
    assert 200 <= r.status_code < 300
    created = r.json()
    assert created["email"] == email
    # GitHub-less signup: no GitHub username on the public payload
    assert created["github_username"] is None
    user = users.get_user_by_email(session=db, email=email)
    assert user is not None
    assert user.account.github_name is None
    assert verify_password(password, user.hashed_password)


def test_register_user_already_exists_error(client: TestClient) -> None:
    password = random_lower_string()
    full_name = random_lower_string()
    data = {
        "email": settings.FIRST_SUPERUSER,
        "password": password,
        "full_name": full_name,
    }
    r = client.post(
        "/users/signup",
        json=data,
    )
    assert r.status_code == 400


def test_github_less_user_cannot_create_project(client: TestClient) -> None:
    """GitHub-less users can sign up but cannot own projects (yet)."""
    email = random_email()
    password = random_lower_string()
    r = client.post(
        "/users/signup",
        json={"email": email, "password": password},
    )
    assert 200 <= r.status_code < 300
    login = client.post(
        "/login/access-token",
        data={"username": email, "password": password},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = client.post(
        "/projects",
        headers=headers,
        json={"name": "ghless-project", "title": "GitHub-less project"},
    )
    assert r.status_code == 403
    assert "GitHub" in r.json()["detail"]


def test_update_user(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = users.create_user(session=db, user_create=user_in)

    data = {"full_name": "Updated_full_name"}
    r = client.patch(
        f"/users/{user.id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    updated_user = r.json()

    assert updated_user["full_name"] == "Updated_full_name"

    user_query = select(User).where(User.email == username)
    user_db = db.exec(user_query).first()
    db.refresh(user_db)
    assert user_db
    assert user_db.full_name == "Updated_full_name"


def test_update_user_not_exists(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"full_name": "Updated_full_name"}
    r = client.patch(
        f"/users/{uuid.uuid4()}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 404
    assert (
        r.json()["detail"]
        == "A user with this ID does not exist in the system"
    )


def test_update_user_email_exists(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = users.create_user(session=db, user_create=user_in)
    username2 = random_email()
    password2 = random_lower_string()
    user_in2 = UserCreate(email=username2, password=password2)
    user2 = users.create_user(session=db, user_create=user_in2)
    data = {"email": user2.email}
    r = client.patch(
        f"/users/{user.id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "User with this email already exists"


def test_delete_user_me(client: TestClient, db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = users.create_user(session=db, user_create=user_in)
    user_id = user.id
    login_data = {
        "username": username,
        "password": password,
    }
    r = client.post("/login/access-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}
    r = client.delete(
        "/user",
        headers=headers,
    )
    assert r.status_code == 200
    deleted_user = r.json()
    assert deleted_user["message"] == "User deleted successfully"
    result = db.exec(select(User).where(User.id == user_id)).first()
    assert result is None

    user_query = select(User).where(User.id == user_id)
    user_db = db.execute(user_query).first()
    assert user_db is None


def test_delete_user_me_as_superuser(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.delete(
        "/user",
        headers=superuser_token_headers,
    )
    assert r.status_code == 403
    response = r.json()
    assert (
        response["detail"]
        == "Super users are not allowed to delete themselves"
    )


def test_delete_user_super_user(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = users.create_user(session=db, user_create=user_in)
    user_id = user.id
    r = client.delete(
        f"/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    deleted_user = r.json()
    assert deleted_user["message"] == "User deleted successfully"
    result = db.exec(select(User).where(User.id == user_id)).first()
    assert result is None


def test_delete_user_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.delete(
        f"/users/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "User not found"


def test_delete_user_current_super_user_error(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    super_user = users.get_user_by_email(
        session=db, email=settings.FIRST_SUPERUSER
    )
    assert super_user
    user_id = super_user.id
    r = client.delete(
        f"/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 403
    assert (
        r.json()["detail"]
        == "Super users are not allowed to delete themselves"
    )


def test_delete_user_without_privileges(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = users.create_user(session=db, user_create=user_in)
    r = client.delete(
        f"/users/{user.id}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "The user doesn't have enough privileges"


def test_post_user_zotero_auth(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    # Look the user up by ID since earlier tests change the test user's email
    r = client.get("/user", headers=normal_user_token_headers)
    user = db.get(User, uuid.UUID(r.json()["id"]))
    assert user
    request_token = {
        "oauth_token": "request-token",
        "oauth_token_secret": "request-token-secret",
    }
    with patch(
        "app.zotero.fetch_request_token", return_value=request_token
    ) as fetch_request_token:
        r = client.post(
            "/user/zotero-auth/start",
            headers=normal_user_token_headers,
        )
    assert r.status_code == 200
    assert "oauth_token=request-token" in r.json()["authorize_url"]
    assert fetch_request_token.call_args.kwargs["callback_uri"].endswith(
        "/auth/zotero"
    )
    # The request token secret is stashed server-side until the flow finishes
    pending = users.get_external_credential(
        session=db, user=user, provider="zotero", label="pending"
    )
    assert pending is not None
    # A verifier for a different request token must not be accepted
    r = client.post(
        "/user/zotero-auth",
        headers=normal_user_token_headers,
        json={"oauth_token": "other-token", "oauth_verifier": "verifier"},
    )
    assert r.status_code == 400
    # A mismatch must not consume the token, so a flow the user still has open
    # in another tab can finish
    assert (
        users.get_external_credential(
            session=db, user=user, provider="zotero", label="pending"
        )
        is not None
    )
    with patch(
        "app.zotero.fetch_access_token",
        return_value={
            "oauth_token": "access-token",
            "oauth_token_secret": "zotero-api-key",
            "userID": "12345",
            "username": "some-user",
        },
    ):
        r = client.post(
            "/user/zotero-auth",
            headers=normal_user_token_headers,
            json={
                "oauth_token": "request-token",
                "oauth_verifier": "verifier",
            },
        )
    assert r.status_code == 200
    db.refresh(user)
    assert users.get_zotero_api_key(session=db, user=user) == "zotero-api-key"
    credential = users.get_external_credential(
        session=db, user=user, provider="zotero"
    )
    assert credential is not None
    assert credential.provider_account_id == "12345"
    assert credential.metadata_json == {"username": "some-user"}
    # The pending request token is cleaned up once it has been used
    assert (
        users.get_external_credential(
            session=db, user=user, provider="zotero", label="pending"
        )
        is None
    )
    r = client.get(
        "/user/connected-accounts",
        headers=normal_user_token_headers,
    )
    assert r.json()["zotero"]
    r = client.delete(
        "/user/external-credentials/zotero",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    assert (
        users.get_external_credential(session=db, user=user, provider="zotero")
        is None
    )


def _github_auth(client: TestClient, headers: dict[str, str], username: str):
    """Drive POST /user/github-auth with GitHub's responses stubbed out."""

    def api_get(url, *args, **kwargs):
        if "login/oauth/access_token" in url:
            return SimpleNamespace(
                status_code=200, text="access_token=gho_fake&scope="
            )
        if url.endswith("/user"):
            return SimpleNamespace(
                status_code=200, json=lambda: {"login": username}
            )
        raise AssertionError(f"unexpected URL: {url}")

    with (
        patch("app.api.routes.users.requests.get", side_effect=api_get),
        patch("app.api.routes.users.users.save_github_token"),
    ):
        return client.post(
            "/user/github-auth",
            headers=headers,
            json={"code": "c", "redirect_uri": "http://localhost/x"},
        )


def test_post_user_github_auth_links_without_renaming(
    client: TestClient, db: Session
) -> None:
    from app.tests import authentication_token_from_email

    suffix = uuid.uuid4().hex[:8]
    # Linking records the GitHub name and nothing else: the account name
    # is what project URLs and object storage paths are keyed by, so it
    # never changes, even when it differs and the GitHub name is free.
    fresh = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"fresh-{suffix}@example.com",
            password="testpassword123",
            account_name=f"fresh{suffix}",
        ),
    )
    headers = authentication_token_from_email(
        client=client, email=fresh.email, db=db
    )
    username = f"GhFresh{suffix}"
    r = _github_auth(client, headers, username)
    assert r.status_code == 200, r.text
    db.refresh(fresh)
    assert fresh.account.github_name == username
    assert fresh.account.name == f"fresh{suffix}"
    # Reauthorizing with the same identity is fine and changes nothing.
    r = _github_auth(client, headers, username)
    assert r.status_code == 200, r.text
    db.refresh(fresh)
    assert fresh.account.name == f"fresh{suffix}"
    # A different GitHub identity can't replace the one already linked.
    r = _github_auth(client, headers, f"ghother{suffix}")
    assert r.status_code == 400
    # And one that belongs to another account is refused outright.
    other = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"other-{suffix}@example.com",
            password="testpassword123",
            account_name=f"other{suffix}",
        ),
    )
    other_headers = authentication_token_from_email(
        client=client, email=other.email, db=db
    )
    r = _github_auth(client, other_headers, username)
    assert r.status_code == 409


def test_email_verification(client: TestClient, db: Session) -> None:
    from datetime import timedelta

    from app.core import utcnow
    from app.security import (
        generate_email_verification_token,
        generate_password_reset_token,
    )
    from app.tests import authentication_token_from_email

    suffix = uuid.uuid4().hex[:8]
    user = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"verify-{suffix}@example.com",
            password="testpassword123",
            account_name=f"verify{suffix}",
        ),
    )
    headers = authentication_token_from_email(
        client=client, email=user.email, db=db
    )
    base = "/user/email-verification"
    # A password signup starts out unverified
    r = client.get("/user", headers=headers)
    assert r.json()["email_verified"] is False
    # Nothing to confirm before a code has been sent
    r = client.post(
        f"{base}/confirm", json={"code": "123456"}, headers=headers
    )
    assert r.status_code == 400
    sent: list[dict] = []
    with (
        patch(
            "app.api.routes.users.send_email",
            side_effect=lambda **kw: sent.append(kw),
        ),
        patch("app.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.config.settings.EMAILS_FROM_EMAIL", "noreply@example.com"),
    ):
        r = client.post(base, headers=headers)
        assert r.status_code == 200, r.text
        assert len(sent) == 1
        assert sent[0]["email_to"] == user.email
        # The message carries the code and a link with a token
        code = sent[0]["subject"].split()[-1]
        assert len(code) == 6 and code.isdigit()
        assert code in sent[0]["html_content"]
        assert "/verify-email?token=" in sent[0]["html_content"]
        # Only the hash is stored
        db.refresh(user)
        assert user.email_verification is not None
        assert code not in user.email_verification.code_hash
        # Asking again right away is refused
        r = client.post(base, headers=headers)
        assert r.status_code == 429
    # A wrong code doesn't verify, and is counted
    wrong = "000000" if code != "000000" else "111111"
    r = client.post(f"{base}/confirm", json={"code": wrong}, headers=headers)
    assert r.status_code == 400
    db.refresh(user)
    assert user.email_verification is not None
    assert user.email_verification.attempts == 1
    assert user.email_verified is False
    # A malformed code is rejected before it counts
    r = client.post(f"{base}/confirm", json={"code": "12"}, headers=headers)
    assert r.status_code == 422
    # The right code verifies and comes back on the user
    r = client.post(f"{base}/confirm", json={"code": code}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["email_verified"] is True
    db.refresh(user)
    assert user.email_verified_at is not None
    assert user.email_verification is None
    # Once verified there's nothing more to send
    r = client.post(base, headers=headers)
    assert r.status_code == 400
    # An expired code is thrown away rather than accepted
    user.email_verified_at = None
    db.add(user)
    db.commit()
    code, _ = users.create_email_verification(session=db, user=user)
    assert user.email_verification is not None
    user.email_verification.expires = utcnow() - timedelta(minutes=1)
    db.add(user.email_verification)
    db.commit()
    r = client.post(f"{base}/confirm", json={"code": code}, headers=headers)
    assert r.status_code == 400
    assert "expired" in r.json()["detail"]
    db.refresh(user)
    assert user.email_verification is None
    # Too many wrong guesses discards the code
    code, _ = users.create_email_verification(session=db, user=user)
    for _ in range(users.EMAIL_VERIFICATION_MAX_ATTEMPTS):
        r = client.post(
            f"{base}/confirm",
            json={"code": "000000" if code != "000000" else "111111"},
            headers=headers,
        )
        assert r.status_code == 400
    db.refresh(user)
    assert user.email_verification is None
    r = client.post(f"{base}/confirm", json={"code": code}, headers=headers)
    assert r.status_code == 400
    # The link in the email verifies without being logged in, but only a
    # verification token for the address the user still has
    verify_url = "/verify-email"
    r = client.post(
        verify_url, json={"token": generate_password_reset_token(user.email)}
    )
    assert r.status_code == 400
    stale = generate_email_verification_token(
        user_id=user.id, email=f"old-{suffix}@example.com"
    )
    r = client.post(verify_url, json={"token": stale})
    assert r.status_code == 400
    r = client.post(verify_url, json={"token": "not-a-token"})
    assert r.status_code == 400
    token = generate_email_verification_token(
        user_id=user.id, email=user.email
    )
    r = client.post(verify_url, json={"token": token})
    assert r.status_code == 200, r.text
    db.refresh(user)
    assert user.email_verified is True
    r = client.get("/user", headers=headers)
    assert r.json()["email_verified"] is True


def test_onboarding_flags_round_trip(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    """Account and project flags are set, listed, and cleared separately."""
    from app.models import Project
    from app.tests import authentication_token_from_email, create_random_user

    base = "/user/onboarding-flags"
    # Start from a known state, since the normal user is shared by tests.
    for step in ["cli", "editor", "dismissed"]:
        client.delete(
            base, headers=normal_user_token_headers, params={"step": step}
        )
    response = client.get(base, headers=normal_user_token_headers)
    assert response.status_code == 200
    assert response.json()["account"] == []
    # An account-level flag lands under "account", not under a project.
    response = client.put(
        base, headers=normal_user_token_headers, json={"step": "cli"}
    )
    assert response.status_code == 200
    body = client.get(base, headers=normal_user_token_headers).json()
    assert body["account"] == ["cli"]
    # Setting the same flag twice is a no-op rather than a duplicate.
    response = client.put(
        base, headers=normal_user_token_headers, json={"step": "cli"}
    )
    assert response.status_code == 200
    body = client.get(base, headers=normal_user_token_headers).json()
    assert body["account"] == ["cli"]
    # A project the user can read takes flags keyed by its ID.
    owner = create_random_user(db)
    project = Project(
        name=f"onboarding-{uuid.uuid4().hex[:8]}",
        title="Onboarding flags project",
        git_repo_url="https://github.com/someone/onboarding",
        owner_account_id=owner.account.id,
        owner_account=owner.account,
        is_public=True,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    response = client.put(
        base,
        headers=normal_user_token_headers,
        json={"step": "editor", "project_id": str(project.id)},
    )
    assert response.status_code == 200
    body = client.get(base, headers=normal_user_token_headers).json()
    assert body["projects"][str(project.id)] == ["editor"]
    # The owner's first project is named, for tips that belong only there;
    # this user doesn't own it, so it isn't theirs
    owner_headers = authentication_token_from_email(
        client=client, email=owner.email, db=db
    )
    owner_body = client.get(base, headers=owner_headers).json()
    assert owner_body["first_project_id"] == str(project.id)
    assert body.get("first_project_id") != str(project.id)
    # The account list is untouched by a project-scoped flag.
    assert body["account"] == ["cli"]
    # Two requests for the same flag at once (a double-click) both pass the
    # existence check; the unique constraint settles it and the loser still
    # gets a 200. Simulated by blinding the check so the insert collides.
    import sqlalchemy

    import app.api.routes.users as users_routes
    from app.models import UserOnboardingFlag

    real_select = users_routes.select

    def blind_select(*args):
        stmt = real_select(*args)
        if args and args[0] is UserOnboardingFlag:
            return stmt.where(sqlalchemy.false())
        return stmt

    with patch.object(users_routes, "select", blind_select):
        response = client.put(
            base,
            headers=normal_user_token_headers,
            json={"step": "editor", "project_id": str(project.id)},
        )
    assert response.status_code == 200, response.text
    body = client.get(base, headers=normal_user_token_headers).json()
    assert body["projects"][str(project.id)] == ["editor"]
    # Deleting is scoped the same way: the project flag survives clearing
    # the account one.
    client.delete(
        base, headers=normal_user_token_headers, params={"step": "cli"}
    )
    body = client.get(base, headers=normal_user_token_headers).json()
    assert body["account"] == []
    assert body["projects"][str(project.id)] == ["editor"]
    client.delete(
        base,
        headers=normal_user_token_headers,
        params={"step": "editor", "project_id": str(project.id)},
    )
    body = client.get(base, headers=normal_user_token_headers).json()
    assert body["projects"].get(str(project.id), []) == []
    # A project that doesn't exist can't be flagged.
    response = client.put(
        base,
        headers=normal_user_token_headers,
        json={"step": "editor", "project_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404
    # Neither can a private project the user has no access to.
    private = Project(
        name=f"private-{uuid.uuid4().hex[:8]}",
        title="Private project",
        git_repo_url="https://github.com/someone/private",
        owner_account_id=owner.account.id,
        owner_account=owner.account,
        is_public=False,
    )
    db.add(private)
    db.commit()
    db.refresh(private)
    response = client.put(
        base,
        headers=normal_user_token_headers,
        json={"step": "editor", "project_id": str(private.id)},
    )
    assert response.status_code == 403
    # Resetting clears everything at once, account and project alike.
    client.put(base, headers=normal_user_token_headers, json={"step": "cli"})
    client.put(
        base,
        headers=normal_user_token_headers,
        json={"step": "editor", "project_id": str(project.id)},
    )
    response = client.delete(base, headers=normal_user_token_headers)
    assert response.status_code == 200
    body = client.get(base, headers=normal_user_token_headers).json()
    assert body["account"] == []
    assert body["projects"] == {}
    # Resetting again is harmless rather than an error.
    assert (
        client.delete(base, headers=normal_user_token_headers)
    ).status_code == 200
    # Flags require a session at all.
    assert client.get(base).status_code == 401
    assert client.delete(base).status_code == 401


def test_read_users_search_and_sort(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Superusers can find a user and order the list by signup time."""
    from app import users as users_mod

    url = "/users"
    marker = uuid.uuid4().hex[:8]
    first = users_mod.create_user(
        session=db,
        user_create=UserCreate(
            email=f"alpha-{marker}@example.com",
            password="testpassword123",
            full_name=f"Alpha {marker}",
            github_username=f"alphagh{marker}",
        ),
    )
    second = users_mod.create_user(
        session=db,
        user_create=UserCreate(
            email=f"beta-{marker}@example.com",
            password="testpassword123",
            full_name=f"Beta {marker}",
        ),
    )
    # Every user carries when they signed up, which is what sorting uses.
    assert first.created is not None
    # Searching matches email...
    body = client.get(
        url, headers=superuser_token_headers, params={"search_for": marker}
    ).json()
    assert body["count"] == 2
    assert {u["email"] for u in body["data"]} == {first.email, second.email}
    # ...full name, and GitHub username, which lives on the account.
    for term, expected in [
        (f"Alpha {marker}", {first.email}),
        (f"alphagh{marker}", {first.email}),
    ]:
        body = client.get(
            url, headers=superuser_token_headers, params={"search_for": term}
        ).json()
        assert {u["email"] for u in body["data"]} == expected
    # Newest first by default; flipping the direction reverses it.
    body = client.get(
        url,
        headers=superuser_token_headers,
        params={"search_for": marker, "sort_by": "created"},
    ).json()
    assert [u["email"] for u in body["data"]] == [second.email, first.email]
    body = client.get(
        url,
        headers=superuser_token_headers,
        params={
            "search_for": marker,
            "sort_by": "created",
            "descending": False,
        },
    ).json()
    assert [u["email"] for u in body["data"]] == [first.email, second.email]
    # Sorting by email is available too, and the count reflects the search
    # rather than the whole table.
    body = client.get(
        url,
        headers=superuser_token_headers,
        params={
            "search_for": marker,
            "sort_by": "email",
            "descending": False,
        },
    ).json()
    assert [u["email"] for u in body["data"]] == [first.email, second.email]
    assert body["count"] == 2
    # A search matching nothing is an empty list, not an error.
    body = client.get(
        url,
        headers=superuser_token_headers,
        params={"search_for": "no-such-user-anywhere"},
    ).json()
    assert body["count"] == 0
    assert body["data"] == []
    # LIKE's wildcards in the search are characters to find, not patterns:
    # "a_pha" would otherwise match "alpha", and "%" everything.
    for term in [f"a_pha-{marker}", f"alpha%{marker}", f"{marker}\\"]:
        body = client.get(
            url, headers=superuser_token_headers, params={"search_for": term}
        ).json()
        assert body["count"] == 0, term
        assert body["data"] == []


def test_get_user_github_repos_excludes_collaborations(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Only repos a project can actually be created for, newest first."""
    url = "/user/github/repos"
    calls = []

    def fake_get(request_url, headers=None, params=None):
        calls.append(params)
        # Two full pages then a short one, so pagination has to stop on its
        # own rather than running to the cap.
        page = params["page"]
        count = params["per_page"] if page < 3 else 2
        return SimpleNamespace(
            status_code=200,
            json=lambda: [
                {"full_name": f"owner/repo-{page}-{i}"} for i in range(count)
            ],
            text="",
        )

    with (
        patch(
            "app.api.routes.users.users.get_github_token",
            return_value="gh-token",
        ),
        patch("app.api.routes.users.requests.get", side_effect=fake_get),
    ):
        resp = client.get(url, headers=normal_user_token_headers)
    assert resp.status_code == 200
    # A repo you only collaborate on can't have a project created for it, so
    # asking GitHub for those would offer choices that fail.
    assert calls[0]["affiliation"] == "owner,organization_member"
    # GitHub sorts by full_name unless told otherwise, which buries whatever
    # the user has been working on.
    assert calls[0]["sort"] == "updated"
    # Paged through, and stopped at the short page rather than the cap.
    assert len(calls) == 3
    assert len(resp.json()) == 100 + 100 + 2
    # An explicit page asks for exactly that page.
    with (
        patch(
            "app.api.routes.users.users.get_github_token",
            return_value="gh-token",
        ),
        patch("app.api.routes.users.requests.get", side_effect=fake_get),
    ):
        resp = client.get(
            url, headers=normal_user_token_headers, params={"page": 2}
        )
    assert resp.status_code == 200
    assert calls[-1]["page"] == 2


def test_get_user_github_repos_search(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """A search term goes to GitHub search, scoped to the user and their orgs."""
    from types import SimpleNamespace
    from unittest.mock import patch

    calls: list[tuple[str, dict]] = []

    def fake_get(url, headers=None, params=None):
        calls.append((url, dict(params or {})))
        if url.endswith("/user/orgs"):
            return SimpleNamespace(
                status_code=200, json=lambda: [{"login": "calkit"}]
            )
        assert url.endswith("/search/repositories")
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "items": [
                    {"full_name": "me/boundary-layer-turbulence-modeling"}
                ]
            },
        )

    with (
        patch("app.api.routes.users.requests.get", side_effect=fake_get),
        patch("app.api.routes.users.users.get_github_token", return_value="t"),
    ):
        resp = client.get(
            "/user/github/repos",
            params={"search": "  boundary   layer "},
            headers=normal_user_token_headers,
        )
    assert resp.status_code == 200, resp.text
    assert (
        resp.json()[0]["full_name"] == "me/boundary-layer-turbulence-modeling"
    )
    search_call = next(
        c for c in calls if c[0].endswith("/search/repositories")
    )
    q = search_call[1]["q"]
    assert q.startswith("boundary layer in:name user:")
    assert "org:calkit" in q
    assert search_call[1]["sort"] == "updated"


def test_create_user_derived_account_name_gets_suffix(db: Session) -> None:
    from app import users
    from app.models import UserCreate

    tag = uuid.uuid4().hex[:8]
    first = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"same-{tag}@one.example", password="password123"
        ),
    )
    second = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"same-{tag}@two.example", password="password123"
        ),
    )
    assert first.account.name == f"same-{tag}"
    assert second.account.name == f"same-{tag}-2"
    # A name the user picked is theirs to get wrong
    with pytest.raises(HTTPException) as excinfo:
        users.create_user(
            session=db,
            user_create=UserCreate(
                email=f"other-{tag}@three.example",
                password="password123",
                account_name=f"same-{tag}",
            ),
        )
    assert excinfo.value.status_code == 422
