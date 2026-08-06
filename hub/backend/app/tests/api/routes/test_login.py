import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from app import users
from app.config import settings
from app.core import utcnow
from app.models import DeviceAuth, RefreshToken, User, UserCreate
from app.security import (
    generate_password_reset_token,
    hash_refresh_token,
    verify_password,
)
from fastapi.testclient import TestClient
from sqlmodel import Session, select


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
