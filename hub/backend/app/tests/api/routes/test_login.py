import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import users
from app.config import settings
from app.core import utcnow
from app.models import DeviceAuth, RefreshToken, User, UserCreate
from app.security import (
    generate_password_reset_token,
    hash_refresh_token,
    verify_password,
)


def test_get_access_token(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(
        f"{settings.API_V1_STR}/login/access-token", data=login_data
    )
    tokens = r.json()
    assert r.status_code == 200
    assert "access_token" in tokens
    assert tokens["access_token"]
    assert "refresh_token" in tokens
    assert tokens["refresh_token"]
    assert "expires_in" in tokens
    assert tokens["expires_in"] > 0


def test_refresh_access_token_rotates(
    client: TestClient,
    db: Session,
) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(
        f"{settings.API_V1_STR}/login/access-token", data=login_data
    )
    assert r.status_code == 200
    initial = r.json()
    initial_refresh = initial["refresh_token"]
    r = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": initial_refresh},
    )
    assert r.status_code == 200
    rotated = r.json()
    assert rotated["access_token"]
    assert rotated["refresh_token"]
    assert rotated["refresh_token"] != initial_refresh
    assert rotated["expires_in"] > 0
    # Rotated token should work for authenticated endpoint.
    headers = {"Authorization": f"Bearer {rotated['access_token']}"}
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=headers,
    )
    assert r.status_code == 200
    # Within the rotation grace window the old token still works, so an
    # interrupted rotation (the client reloaded before storing the new token)
    # can retry with it and get a fresh pair instead of being stranded.
    r = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": initial_refresh},
    )
    assert r.status_code == 200
    assert r.json()["refresh_token"] != initial_refresh
    old_hash = hash_refresh_token(initial_refresh)
    old_token = db.exec(
        select(RefreshToken).where(RefreshToken.token_hash == old_hash)
    ).first()
    assert old_token is not None
    # It isn't hard-deactivated; its expiry is shortened to the brief grace
    # window (far below the 90-day default), so it lapses shortly after.
    assert old_token.is_active is True
    assert old_token.expires < utcnow() + timedelta(minutes=5)
    # Once that window passes, the old token is rejected.
    old_token.expires = utcnow() - timedelta(seconds=1)
    db.add(old_token)
    db.commit()
    r = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": initial_refresh},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Refresh token has expired"


def test_refresh_access_token_invalid(client: TestClient) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": "not-a-real-refresh-token"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid refresh token"


def test_refresh_access_token_expired(client: TestClient, db: Session) -> None:
    user = db.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    assert user is not None

    refresh_raw = "expired-refresh-token"
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_raw),
            expires=utcnow() - timedelta(minutes=1),
            description="expired test token",
        )
    )
    db.commit()

    r = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": refresh_raw},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Refresh token has expired"


def test_refresh_access_token_inactive_user(
    client: TestClient, db: Session
) -> None:
    user = users.create_user(
        session=db,
        user_create=UserCreate(
            email="inactive-refresh-user@example.com",
            password="test-password-123",
        ),
    )
    user.is_active = False
    db.add(user)
    db.commit()
    refresh_raw = "inactive-user-refresh-token"
    token_hash = hash_refresh_token(refresh_raw)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires=utcnow() + timedelta(minutes=5),
            description="inactive user token",
        )
    )
    db.commit()
    r = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": refresh_raw},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "User is not active"
    stored = db.exec(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    ).first()
    assert stored is not None
    assert stored.is_active is False


def test_get_access_token_incorrect_password(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": "incorrect",
    }
    r = client.post(
        f"{settings.API_V1_STR}/login/access-token", data=login_data
    )
    assert r.status_code == 400


def test_use_access_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=superuser_token_headers,
    )
    result = r.json()
    assert r.status_code == 200
    assert "email" in result


def test_device_initiate(client: TestClient) -> None:
    r = client.post(f"{settings.API_V1_STR}/login/device")
    assert r.status_code == 200
    data = r.json()
    assert "device_code" in data
    assert "verification_uri" in data
    assert data["verification_uri"].endswith(
        f"?device_code={data['device_code']}"
    )
    assert data["expires_in"] > 0
    assert data["interval"] > 0


def test_device_token_pending(client: TestClient, db: Session) -> None:
    auth_request = DeviceAuth(
        device_code="pending-device-code",
        expires=utcnow() + timedelta(minutes=5),
    )
    db.add(auth_request)
    db.commit()
    r = client.post(
        f"{settings.API_V1_STR}/login/device/token",
        json={"device_code": auth_request.device_code},
    )
    assert r.status_code == 202
    assert r.json() == {"detail": "Authorization pending"}


def test_device_token_expired(client: TestClient, db: Session) -> None:
    auth_request = DeviceAuth(
        device_code="expired-device-code",
        expires=utcnow() - timedelta(minutes=1),
    )
    db.add(auth_request)
    db.commit()
    r = client.post(
        f"{settings.API_V1_STR}/login/device/token",
        json={"device_code": auth_request.device_code},
    )
    assert r.status_code == 400


def test_device_authorize_and_token(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    # Initiate
    r = client.post(f"{settings.API_V1_STR}/login/device")
    assert r.status_code == 200
    device_code = r.json()["device_code"]
    # Authorize (requires auth)
    r = client.post(
        f"{settings.API_V1_STR}/login/device/authorize",
        json={"device_code": device_code},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert r.json() == {"message": "CLI access authorized"}
    # Poll for token — should now succeed
    r = client.post(
        f"{settings.API_V1_STR}/login/device/token",
        json={"device_code": device_code},
    )
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["access_token"]
    assert "refresh_token" in data
    assert data["refresh_token"]
    assert "expires_in" in data
    assert data["expires_in"] > 0
    # Row should be deleted — second poll returns 404
    r = client.post(
        f"{settings.API_V1_STR}/login/device/token",
        json={"device_code": device_code},
    )
    assert r.status_code == 404


def test_device_authorize_requires_auth(
    client: TestClient, db: Session
) -> None:
    auth_request = DeviceAuth(
        device_code="unauthed-device-code",
        expires=utcnow() + timedelta(minutes=5),
    )
    db.add(auth_request)
    db.commit()
    r = client.post(
        f"{settings.API_V1_STR}/login/device/authorize",
        json={"device_code": auth_request.device_code},
    )
    assert r.status_code == 401


def test_device_authorize_expired(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    auth_request = DeviceAuth(
        device_code="expired-auth-code",
        expires=utcnow() - timedelta(minutes=1),
    )
    db.add(auth_request)
    db.commit()
    r = client.post(
        f"{settings.API_V1_STR}/login/device/authorize",
        json={"device_code": auth_request.device_code},
        headers=superuser_token_headers,
    )
    assert r.status_code == 400


@pytest.mark.skip(reason="Password reset not supported with GitHub-only auth")
def test_recovery_password(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with (
        patch("app.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.config.settings.SMTP_USER", "admin@example.com"),
    ):
        email = "test@example.com"
        r = client.post(
            f"{settings.API_V1_STR}/password-recovery/{email}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        assert r.json() == {"message": "Password recovery email sent"}


@pytest.mark.skip(reason="Password reset not supported with GitHub-only auth")
def test_recovery_password_user_not_exits(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    email = "jVgQr@example.com"
    r = client.post(
        f"{settings.API_V1_STR}/password-recovery/{email}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 404


@pytest.mark.skip(reason="Password reset not supported with GitHub-only auth")
def test_reset_password(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    token = generate_password_reset_token(email=settings.FIRST_SUPERUSER)
    data = {"new_password": "changethis", "token": token}
    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    assert r.json() == {"message": "Password updated successfully"}
    user_query = select(User).where(User.email == settings.FIRST_SUPERUSER)
    user = db.exec(user_query).first()
    assert user
    assert verify_password(data["new_password"], user.hashed_password)


@pytest.mark.skip(reason="Password reset not supported with GitHub-only auth")
def test_reset_password_invalid_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"new_password": "changethis", "token": "invalid"}
    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=superuser_token_headers,
        json=data,
    )
    response = r.json()
    assert "detail" in response
    assert r.status_code == 400
    assert response["detail"] == "Invalid token"


class _FakeGoogleResp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_login_with_google_creates_github_less_user(
    client: TestClient, db: Session
) -> None:
    email = f"g-{uuid.uuid4().hex[:8]}@example.com"
    with (
        patch(
            "app.api.routes.login.requests.post",
            return_value=_FakeGoogleResp(
                200, {"access_token": "ya29.fake", "refresh_token": "r"}
            ),
        ),
        patch(
            "app.api.routes.login.requests.get",
            return_value=_FakeGoogleResp(
                200,
                {"email": email, "email_verified": True, "name": "G User"},
            ),
        ),
        patch("app.api.routes.login.users.save_google_token"),
    ):
        r = client.post(
            f"{settings.API_V1_STR}/login/google",
            json={
                "code": "auth-code",
                "redirect_uri": "http://localhost:5173/auth/google",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    user = users.get_user_by_email(session=db, email=email)
    assert user is not None
    # Signed up via Google -> no linked GitHub account.
    assert user.account.github_name is None


def test_login_with_google_requires_verified_email(client: TestClient) -> None:
    with (
        patch(
            "app.api.routes.login.requests.post",
            return_value=_FakeGoogleResp(200, {"access_token": "ya29.fake"}),
        ),
        patch(
            "app.api.routes.login.requests.get",
            return_value=_FakeGoogleResp(
                200, {"email": "x@example.com", "email_verified": False}
            ),
        ),
    ):
        r = client.post(
            f"{settings.API_V1_STR}/login/google",
            json={"code": "c", "redirect_uri": "http://localhost:5173/x"},
        )
    assert r.status_code == 400


class _FakeGitHubResp:
    """Stands in for both the token exchange (.text) and the API (.json())."""

    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def _github_login(
    client: TestClient, username: str, emails: list[dict]
) -> "object":
    """Drive POST /login/github with GitHub's responses stubbed out."""

    # One dispatcher for every GitHub call the flow makes. The route module
    # and app.github share the same imported `requests`, so patching it in
    # two places would just leave the last patch standing.
    def api_get(url, *args, **kwargs):
        if "login/oauth/access_token" in url:
            return _FakeGitHubResp(200, text="access_token=gho_fake&scope=")
        if url.endswith("/user/emails"):
            return _FakeGitHubResp(200, emails)
        if url.endswith("/user"):
            return _FakeGitHubResp(
                200, {"login": username, "email": None, "name": "GH User"}
            )
        raise AssertionError(f"unexpected URL: {url}")

    with (
        patch("app.api.routes.login.requests.get", side_effect=api_get),
        patch("app.api.routes.login.users.save_github_token"),
    ):
        return client.post(
            f"{settings.API_V1_STR}/login/github",
            json={
                "code": "auth-code",
                "redirect_uri": "http://localhost:5173/login",
            },
        )


def test_login_with_github_links_to_existing_account(
    client: TestClient, db: Session
) -> None:
    """A Google-first user signing in with GitHub gets one account, not two."""
    email = f"gh-{uuid.uuid4().hex[:8]}@example.com"
    existing = users.create_user(
        session=db,
        user_create=UserCreate(email=email, password="testpassword123"),
    )
    # Created through Google, which is what proves the address is theirs.
    users.save_google_token(
        session=db,
        user=existing,
        google_resp={
            "access_token": "ya29.x",
            "refresh_token": "r",
            "expires_in": 3600,
        },
        verified_email=email,
    )
    assert existing.account.github_name is None
    username = f"ghuser{uuid.uuid4().hex[:6]}"
    # An unverified address proves nothing about who owns it, so it can't be
    # what attaches a GitHub identity to an account that already exists.
    r = _github_login(
        client,
        username,
        [{"email": email, "primary": True, "verified": False}],
    )
    assert r.status_code == 400, r.text
    db.refresh(existing)
    assert existing.account.github_name is None
    # Verified, and the account is claimed rather than duplicated.
    r = _github_login(
        client, username, [{"email": email, "primary": True, "verified": True}]
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
    db.refresh(existing)
    assert existing.account.github_name == username
    # The account had no projects, so it takes the GitHub name too and
    # `calkit clone owner/project` matches the GitHub URL.
    assert existing.account.name == username.lower()
    # Exactly one user still holds that email -- the duplicate insert this
    # guards against used to surface as a 500.
    assert len(db.exec(select(User).where(User.email == email)).all()) == 1
    # Signing in again resolves by GitHub username and changes nothing.
    r = _github_login(
        client, username, [{"email": email, "primary": True, "verified": True}]
    )
    assert r.status_code == 200, r.text
    # A different GitHub identity claiming the same email is refused, since
    # joining them would move the account's repos to another GitHub owner.
    r = _github_login(
        client,
        f"other{uuid.uuid4().hex[:6]}",
        [{"email": email, "primary": True, "verified": True}],
    )
    assert r.status_code == 400, r.text


def test_login_with_github_refuses_unproven_email_match(
    client: TestClient, db: Session
) -> None:
    """A password account is never handed to whoever shows up with its email.

    Password signup doesn't verify the address, so an account under the
    victim's email may be the attacker's, parked there to collect the
    victim's GitHub identity and token the first time they sign in that way.
    """
    email = f"pw-{uuid.uuid4().hex[:8]}@example.com"
    existing = users.create_user(
        session=db,
        user_create=UserCreate(email=email, password="testpassword123"),
    )
    original_name = existing.account.name
    username = f"ghpw{uuid.uuid4().hex[:6]}"
    verified = [{"email": email, "primary": True, "verified": True}]
    r = _github_login(client, username, verified)
    assert r.status_code == 400, r.text
    # The message points at the path that is safe: prove you hold the
    # account by signing in to it, then connect GitHub from there.
    assert "email and password" in r.json()["detail"]
    assert "settings" in r.json()["detail"]
    db.refresh(existing)
    assert existing.account.github_name is None
    assert existing.account.name == original_name
    # No second user was created for the GitHub identity either.
    assert len(db.exec(select(User).where(User.email == email)).all()) == 1
    # A Google account connected from settings is any Google account, so it
    # says nothing about this email and doesn't unlock the link.
    users.save_google_token(
        session=db,
        user=existing,
        google_resp={
            "access_token": "ya29.x",
            "refresh_token": "r",
            "expires_in": 3600,
        },
    )
    r = _github_login(client, username, verified)
    assert r.status_code == 400, r.text
    db.refresh(existing)
    assert existing.account.github_name is None
    # Nor does one Google vouched for under a different address.
    users.save_google_token(
        session=db,
        user=existing,
        google_resp={
            "access_token": "ya29.x",
            "refresh_token": "r",
            "expires_in": 3600,
        },
        verified_email=f"other-{email}",
    )
    r = _github_login(client, username, verified)
    assert r.status_code == 400, r.text
    # Once Google has vouched for this address, the match is evidence.
    users.save_google_token(
        session=db,
        user=existing,
        google_resp={
            "access_token": "ya29.x",
            "refresh_token": "r",
            "expires_in": 3600,
        },
        verified_email=email.upper(),
    )
    r = _github_login(client, username, verified)
    assert r.status_code == 200, r.text
    db.refresh(existing)
    assert existing.account.github_name == username
    # A later Google save that doesn't know the address keeps the proof
    # rather than clearing it.
    users.save_google_token(
        session=db,
        user=existing,
        google_resp={
            "access_token": "ya29.x",
            "refresh_token": "r",
            "expires_in": 3600,
        },
    )
    assert users.email_is_verified(session=db, user=existing)


def test_login_with_github_creates_user_for_a_new_email(
    client: TestClient, db: Session
) -> None:
    email = f"new-{uuid.uuid4().hex[:8]}@example.com"
    username = f"ghnew{uuid.uuid4().hex[:6]}"
    r = _github_login(
        client, username, [{"email": email, "primary": True, "verified": True}]
    )
    assert r.status_code == 200, r.text
    user = users.get_user_by_email(session=db, email=email)
    assert user is not None
    assert user.account.github_name == username
    # A GitHub username already taken as an account name doesn't block the
    # signup; the account name gets a suffix instead.
    other_email = f"new2-{uuid.uuid4().hex[:8]}@example.com"
    r = _github_login(
        client,
        username,
        [{"email": other_email, "primary": True, "verified": True}],
    )
    # Same GitHub username, different email: resolved by username, so it logs
    # in as the first user rather than making another.
    assert r.status_code == 200, r.text
    assert users.get_user_by_email(session=db, email=other_email) is None


def test_login_with_github_keeps_account_name_when_projects_exist(
    client: TestClient, db: Session
) -> None:
    """A rename would break every URL and DVC remote pointing at the old name."""
    from app.models import Project

    email = f"named-{uuid.uuid4().hex[:8]}@example.com"
    existing = users.create_user(
        session=db,
        user_create=UserCreate(email=email, password="testpassword123"),
    )
    users.save_google_token(
        session=db,
        user=existing,
        google_resp={
            "access_token": "ya29.x",
            "refresh_token": "r",
            "expires_in": 3600,
        },
        verified_email=email,
    )
    original_name = existing.account.name
    db.add(
        Project(
            name=f"proj-{uuid.uuid4().hex[:8]}",
            title="An existing project",
            git_repo_url="https://github.com/someone/thing",
            owner_account_id=existing.account.id,
            owner_account=existing.account,
        )
    )
    db.commit()
    username = f"ghkeep{uuid.uuid4().hex[:6]}"
    r = _github_login(
        client, username, [{"email": email, "primary": True, "verified": True}]
    )
    assert r.status_code == 200, r.text
    db.refresh(existing)
    # Linked, but the name the project's URL uses is left alone.
    assert existing.account.github_name == username
    assert existing.account.name == original_name
