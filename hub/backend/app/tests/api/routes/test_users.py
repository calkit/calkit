import uuid
from unittest.mock import patch

from app import users
from app.config import settings
from app.models import User, UserCreate
from app.security import verify_password
from app.tests import random_email, random_lower_string
from fastapi.testclient import TestClient
from sqlmodel import Session, select


def test_get_users_superuser_me(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/user", headers=superuser_token_headers
    )
    current_user = r.json()
    assert current_user
    assert current_user["is_active"] is True
    assert current_user["is_superuser"]
    assert current_user["email"] == settings.FIRST_SUPERUSER


def test_get_users_normal_user_me(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/user", headers=normal_user_token_headers
    )
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
            f"{settings.API_V1_STR}/users",
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
        f"{settings.API_V1_STR}/users/{user_id}",
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
    r = client.post(
        f"{settings.API_V1_STR}/login/access-token", data=login_data
    )
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}
    r = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
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
        f"{settings.API_V1_STR}/users/{uuid.uuid4()}",
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
        f"{settings.API_V1_STR}/users",
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
        f"{settings.API_V1_STR}/users",
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
    r = client.get(
        f"{settings.API_V1_STR}/users/", headers=superuser_token_headers
    )
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
        f"{settings.API_V1_STR}/user",
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
        f"{settings.API_V1_STR}/user/password",
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
        f"{settings.API_V1_STR}/user/password",
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
        f"{settings.API_V1_STR}/user/password",
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
        f"{settings.API_V1_STR}/user",
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
        f"{settings.API_V1_STR}/user/password",
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
        f"{settings.API_V1_STR}/users/signup",
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
        f"{settings.API_V1_STR}/users/signup",
        json=data,
    )
    assert r.status_code == 400


def test_github_less_user_cannot_create_project(client: TestClient) -> None:
    """GitHub-less users can sign up but cannot own projects (yet)."""
    email = random_email()
    password = random_lower_string()
    r = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": email, "password": password},
    )
    assert 200 <= r.status_code < 300
    login = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = client.post(
        f"{settings.API_V1_STR}/projects",
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
        f"{settings.API_V1_STR}/users/{user.id}",
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
        f"{settings.API_V1_STR}/users/{uuid.uuid4()}",
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
        f"{settings.API_V1_STR}/users/{user.id}",
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
    r = client.post(
        f"{settings.API_V1_STR}/login/access-token", data=login_data
    )
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}
    r = client.delete(
        f"{settings.API_V1_STR}/user",
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
        f"{settings.API_V1_STR}/user",
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
        f"{settings.API_V1_STR}/users/{user_id}",
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
        f"{settings.API_V1_STR}/users/{uuid.uuid4()}",
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
        f"{settings.API_V1_STR}/users/{user_id}",
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
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "The user doesn't have enough privileges"


def test_post_user_zotero_auth(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    # Look the user up by ID since earlier tests change the test user's email
    r = client.get(
        f"{settings.API_V1_STR}/user", headers=normal_user_token_headers
    )
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
            f"{settings.API_V1_STR}/user/zotero-auth/start",
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
        f"{settings.API_V1_STR}/user/zotero-auth",
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
            f"{settings.API_V1_STR}/user/zotero-auth",
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
        f"{settings.API_V1_STR}/user/connected-accounts",
        headers=normal_user_token_headers,
    )
    assert r.json()["zotero"]
    r = client.delete(
        f"{settings.API_V1_STR}/user/external-credentials/zotero",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    assert (
        users.get_external_credential(session=db, user=user, provider="zotero")
        is None
    )
