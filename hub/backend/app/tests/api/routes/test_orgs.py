"""Tests for the org routes."""

import threading
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session, select

from app import users
from app.db import engine
from app.models import (
    ROLE_IDS,
    Account,
    Org,
    OrgSubscription,
    User,
    UserCreate,
    UserOrgMembership,
)
from app.subscriptions import PLAN_IDS
from app.tests import authentication_token_from_email


def test_post_org(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    github_name = f"Org-{uuid.uuid4().hex[:8]}"
    install_status = 404
    membership: tuple[int, dict[str, str]] = (404, {})

    def fake_get(
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> SimpleNamespace:
        if url.endswith("/installation"):
            return SimpleNamespace(
                status_code=install_status, json=lambda: {"id": 1}, text=""
            )
        if "/memberships/" in url:
            code, body = membership
            return SimpleNamespace(status_code=code, json=lambda: body)
        return SimpleNamespace(status_code=200, json=lambda: {"name": None})

    def post() -> Response:
        with (
            patch("app.api.routes.orgs.requests.get", side_effect=fake_get),
            patch("app.api.routes.orgs.get_github_token", return_value="t"),
            patch("app.github.create_app_token", return_value="jwt"),
        ):
            return client.post(
                "/orgs",
                json={"github_name": github_name},
                headers=normal_user_token_headers,
            )

    # Without the app installed, not even a GitHub admin can add the org
    membership = (200, {"role": "admin", "state": "active"})
    resp = post()
    assert resp.status_code == 400
    assert "not installed" in resp.json()["detail"]
    # A failed lookup isn't reported as a missing installation
    install_status = 500
    assert post().status_code == 502
    # Someone outside the org can't add it
    install_status = 200
    membership = (404, {})
    assert post().status_code == 404
    # Nor can someone only invited to it
    membership = (200, {"role": "member", "state": "pending"})
    resp = post()
    assert resp.status_code == 400
    assert "pending invitation" in resp.json()["detail"]
    # A plain member can, and becomes the owner in Calkit
    membership = (200, {"role": "member", "state": "active"})
    resp = post()
    assert resp.status_code == 200, resp.text
    org = resp.json()
    assert org["name"] == github_name.lower()
    assert org["github_name"] == github_name
    assert org["display_name"] == github_name
    assert org["role"] == "owner"
    # And it can only be added once
    resp = post()
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]
    # One added along with a repo by an outside collaborator has no members,
    # so a member from GitHub can still claim it
    github_name = f"Org-{uuid.uuid4().hex[:8]}"
    org = Org(
        account=Account(
            name=github_name.lower(),
            display_name="Unclaimed",
            github_name=github_name,
        )
    )
    db.add(org)
    db.commit()
    membership = (200, {"role": "member", "state": "pending"})
    assert post().status_code == 400
    membership = (200, {"role": "member", "state": "active"})
    resp = post()
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(org.id)
    assert resp.json()["display_name"] == "Unclaimed"
    assert resp.json()["role"] == "owner"
    # After which it's taken
    resp = post()
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]


def _make_user(db: Session, prefix: str) -> User:
    suffix = uuid.uuid4().hex[:8]
    return users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"{prefix}-{suffix}@example.com",
            password="testpassword123",
            account_name=f"{prefix}{suffix}",
            github_username=f"{prefix}{suffix}",
        ),
    )


def _make_org(db: Session, owner: User) -> Org:
    # One seat on the free plan, as post_org creates it
    name = f"org{uuid.uuid4().hex[:8]}"
    org = Org(
        account=Account(name=name, display_name=name, github_name=name),
        user_memberships=[
            UserOrgMembership(user=owner, role_id=ROLE_IDS["owner"])
        ],
        subscription=OrgSubscription(
            plan_id=PLAN_IDS["free"],
            n_users=1,
            price=0.0,
            period_months=1,
            subscriber_user_id=owner.id,
        ),
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _headers(client: TestClient, db: Session, user: User) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=user.email, db=db
    )


def _members(
    client: TestClient, org: Org, headers: dict[str, str]
) -> dict[str, str]:
    resp = client.get(f"/orgs/{org.account.name}/users", headers=headers)
    assert resp.status_code == 200, resp.text
    return {u["name"]: u["role"] for u in resp.json()}


def test_get_org_users_and_add_org_member(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    owner = _make_user(db, "owner")
    org = _make_org(db, owner)
    outsider = _make_user(db, "outsider")
    outsider_headers = _headers(client, db, outsider)
    # Only members can list an org's users, unless they're a superuser
    resp = client.get(
        f"/orgs/{org.account.name}/users", headers=outsider_headers
    )
    assert resp.status_code == 403
    assert _members(client, org, superuser_token_headers) == {
        owner.account.name: "owner"
    }
    # The owner is held to the org's single seat
    new_member = _make_user(db, "member")
    url = f"/orgs/{org.account.name}/members"
    body = {"username": new_member.account.name, "role": "write"}
    resp = client.post(url, headers=_headers(client, db, owner), json=body)
    assert resp.status_code == 400
    assert "seats" in resp.json()["detail"]
    # A superuser isn't, even without being a member
    resp = client.post(url, headers=superuser_token_headers, json=body)
    assert resp.status_code == 200, resp.text
    assert _members(client, org, superuser_token_headers) == {
        owner.account.name: "owner",
        new_member.account.name: "write",
    }
    resp = client.post(url, headers=superuser_token_headers, json=body)
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]
    # Someone else outside the org can't add members, even themselves
    resp = client.post(
        url,
        headers=outsider_headers,
        json={"username": outsider.account.name, "role": "owner"},
    )
    assert resp.status_code == 403


def test_update_and_delete_org_member(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    owner = _make_user(db, "owner")
    org = _make_org(db, owner)
    admin = _make_user(db, "admin")
    member = _make_user(db, "member")
    base = f"/orgs/{org.account.name}/members"
    for user, role in [(admin, "admin"), (member, "read")]:
        resp = client.post(
            base,
            headers=superuser_token_headers,
            json={"username": user.account.name, "role": role},
        )
        assert resp.status_code == 200, resp.text
    admin_headers = _headers(client, db, admin)
    member_headers = _headers(client, db, member)
    # Admins can change roles below owner
    resp = client.patch(
        f"{base}/{member.account.name}",
        headers=admin_headers,
        json={"role": "write"},
    )
    assert resp.status_code == 200, resp.text
    # But can't grant ownership or change an owner
    resp = client.patch(
        f"{base}/{member.account.name}",
        headers=admin_headers,
        json={"role": "owner"},
    )
    assert resp.status_code == 403
    resp = client.patch(
        f"{base}/{owner.account.name}",
        headers=admin_headers,
        json={"role": "read"},
    )
    assert resp.status_code == 403
    resp = client.delete(f"{base}/{owner.account.name}", headers=admin_headers)
    assert resp.status_code == 403
    # Members without admin rights can't change anyone
    resp = client.patch(
        f"{base}/{admin.account.name}",
        headers=member_headers,
        json={"role": "read"},
    )
    assert resp.status_code == 403
    resp = client.delete(
        f"{base}/{admin.account.name}", headers=member_headers
    )
    assert resp.status_code == 403
    # Nobody can demote or remove the last owner, not even a superuser
    resp = client.patch(
        f"{base}/{owner.account.name}",
        headers=superuser_token_headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 400
    resp = client.delete(
        f"{base}/{owner.account.name}", headers=superuser_token_headers
    )
    assert resp.status_code == 400
    # Once there's another, a superuser can
    resp = client.patch(
        f"{base}/{member.account.name}",
        headers=superuser_token_headers,
        json={"role": "owner"},
    )
    assert resp.status_code == 200, resp.text
    resp = client.patch(
        f"{base}/{owner.account.name}",
        headers=superuser_token_headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 200, resp.text
    assert _members(client, org, superuser_token_headers) == {
        owner.account.name: "admin",
        admin.account.name: "admin",
        member.account.name: "owner",
    }
    # Owners can remove members
    resp = client.delete(
        f"{base}/{admin.account.name}", headers=member_headers
    )
    assert resp.status_code == 200, resp.text
    # Users who aren't members can't be changed or removed
    resp = client.patch(
        f"{base}/{admin.account.name}",
        headers=superuser_token_headers,
        json={"role": "read"},
    )
    assert resp.status_code == 404
    resp = client.delete(
        f"{base}/{admin.account.name}", headers=superuser_token_headers
    )
    assert resp.status_code == 404
    assert _members(client, org, superuser_token_headers) == {
        owner.account.name: "admin",
        member.account.name: "owner",
    }


def test_concurrent_owner_changes_keep_an_owner(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    owner = _make_user(db, "owner")
    org = _make_org(db, owner)
    other_owner = _make_user(db, "owner")
    base = f"/orgs/{org.account.name}/members"
    resp = client.post(
        base,
        headers=superuser_token_headers,
        json={"username": other_owner.account.name, "role": "owner"},
    )
    assert resp.status_code == 200, resp.text
    results: list[Response] = []

    def demote_other_owner() -> None:
        results.append(
            client.patch(
                f"{base}/{other_owner.account.name}",
                headers=superuser_token_headers,
                json={"role": "admin"},
            )
        )

    # Another transaction holds the org's lock while it demotes the first owner
    with Session(engine) as other:
        other.exec(select(Org).where(Org.id == org.id).with_for_update()).one()
        thread = threading.Thread(target=demote_other_owner)
        thread.start()
        # So the request waits rather than counting two owners
        thread.join(timeout=1)
        assert thread.is_alive()
        membership = other.exec(
            select(UserOrgMembership)
            .where(UserOrgMembership.org_id == org.id)
            .where(UserOrgMembership.user_id == owner.id)
        ).one()
        membership.role_id = ROLE_IDS["admin"]
        other.add(membership)
        other.commit()
    thread.join(timeout=30)
    assert not thread.is_alive()
    # Then sees the other owner is the last one
    assert results[0].status_code == 400, results[0].text
    assert "last owner" in results[0].json()["detail"]
