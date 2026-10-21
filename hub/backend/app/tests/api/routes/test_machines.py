import base64
import time
import uuid
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Literal
from unittest.mock import Mock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException
from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session, select
from starlette.websockets import WebSocketDisconnect

from app import users
from app.api.routes import machines
from app.config import settings
from app.core import utcnow
from app.models import (
    Machine,
    Project,
    RefreshToken,
    User,
    UserProjectAccess,
    UserToken,
    UserTOTP,
)
from app.models.core import ROLE_IDS
from app.security import (
    create_access_token,
    create_machine_grant,
    create_second_factor_token,
    encrypt_secret,
    generate_email_verification_token,
    generate_totp_secret,
)
from app.users import SECOND_FACTOR_REQUIRED, SECOND_FACTOR_SETUP_REQUIRED


@pytest.fixture(autouse=True)
def _machines_for_everyone(monkeypatch: pytest.MonkeyPatch) -> None:
    # The tests' users aren't superusers
    monkeypatch.setattr(machines, "MACHINES_FOR_EVERYONE", True)


def test_machines(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    from app.main import app

    def make_jwk() -> dict[str, str]:
        def b64url(n: int) -> str:
            return base64.urlsafe_b64encode(n.to_bytes(32, "big")).decode()[
                :-1
            ]

        key = ec.generate_private_key(ec.SECP256R1()).public_key()
        numbers = key.public_numbers()
        return {
            "kty": "EC",
            "crv": "P-256",
            "x": b64url(numbers.x),
            "y": b64url(numbers.y),
        }

    # A client of its own, since it keeps the second factor cookie
    client = TestClient(app)
    hostname = f"Lab-Box-{uuid.uuid4().hex[:6]}"
    # What a browser sends to connect: the public half of a key it made
    jwk = make_jwk()
    browser_key = {"public_key": jwk}
    # And the machine's own, which it signs its replies with
    machine_jwk = make_jwk()

    def relay_token(
        headers: dict[str, str],
        second_factor: str | None,
        key: dict[str, Any] | None = None,
    ) -> Response:
        client.cookies.clear()
        if second_factor is not None:
            client.cookies.set(users.SECOND_FACTOR_COOKIE, second_factor)
        return client.post(
            f"/machines/{op['id']}/relay-token",
            json=key or browser_key,
            headers=headers,
        )

    # Only superusers can link machines until they're open to everyone
    with patch.object(machines, "MACHINES_FOR_EVERYONE", False):
        r = client.post(
            "/machines",
            headers=normal_user_token_headers,
            json={"hostname": hostname},
        )
    assert r.status_code == 403
    assert "isn't available" in r.json()["detail"]
    # Registering takes a verified email, since that's what setting up the
    # second factor for opening sessions proves itself with
    me = client.get("/user", headers=normal_user_token_headers).json()
    user = db.get(User, uuid.UUID(me["id"]))
    assert user is not None
    user.email_verified_at = None
    db.add(user)
    db.commit()
    r = client.post(
        "/machines",
        headers=normal_user_token_headers,
        json={"hostname": hostname},
    )
    assert r.status_code == 403
    user.email_verified_at = utcnow()
    db.add(user)
    db.commit()
    # Names are lowercase letters, digits, and dashes
    for name in ["Lab Box", "-lab", "lab_box", "a" * 65, ""]:
        r = client.post(
            "/machines",
            headers=normal_user_token_headers,
            json={"name": name},
        )
        assert r.status_code == 422, name
    # As are hosts, with limits, and keys have to be on the curve
    for bad in [
        {"hosts": ["h"] * 21},
        {"hosts": ["h" * 256]},
        {"public_key": machine_jwk | {"y": machine_jwk["x"]}},
    ]:
        r = client.post(
            "/machines", headers=normal_user_token_headers, json=bad
        )
        assert r.status_code == 422, bad
    # Names default to the slugified hostname, suffixed until unique, and the
    # owner hears about each one registered, so one they didn't expect
    # stands out
    with patch("app.api.routes.machines.send_email") as send:
        r = client.post(
            "/machines",
            headers=normal_user_token_headers,
            json={
                "hostname": hostname,
                "platform": "linux",
                "machine_id": "m-123",
            },
        )
    assert r.status_code == 200, r.text
    op = r.json()
    assert send.call_args.kwargs["email_to"] == user.email
    assert op["name"] in send.call_args.kwargs["subject"]
    assert "m-123" in send.call_args.kwargs["html_content"]
    assert op["system_machine_id"] == "m-123"
    assert op["name"] == hostname.lower()
    assert op["hosts"] == [hostname]
    assert op["token"].startswith("ckm_")
    assert not op["is_online"]
    op_headers = {"Authorization": f"Bearer {op['token']}"}
    r = client.post(
        "/machines",
        headers=normal_user_token_headers,
        json={"hostname": hostname},
    )
    assert r.json()["name"] == f"{hostname.lower()}-2"
    # An explicit name that's taken is refused rather than suffixed
    r = client.post(
        "/machines",
        headers=normal_user_token_headers,
        json={"name": op["name"]},
    )
    assert r.status_code == 409
    # An explicit name is kept whole, even past the length hostnames are
    # cut to
    long_name = "a" * 60 + uuid.uuid4().hex[:4]
    for status in (200, 409):
        r = client.post(
            "/machines",
            headers=normal_user_token_headers,
            json={"name": long_name},
        )
        assert r.status_code == status, r.text
        if status == 200:
            assert r.json()["name"] == long_name
    # A machine can check it's still registered with its own token
    r = client.get("/machines/self", headers=op_headers)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == op["id"]
    r = client.get("/machines/self", headers=normal_user_token_headers)
    assert r.status_code == 403
    # Machine tokens only work for machine routes, and vice versa
    assert client.get("/user", headers=op_headers).status_code == 403
    r = client.post(
        "/machines/check-in", headers=normal_user_token_headers, json={}
    )
    assert r.status_code == 403
    # Check in with workspaces from two projects
    project = f"someone/proj-{uuid.uuid4().hex[:6]}"
    r = client.post(
        "/machines/check-in",
        headers=op_headers,
        json={
            "calkit_version": "1.2.3",
            "workspaces": [
                {"path": "/home/me/calkit/a", "project": project.upper()},
                {"path": "/home/me/calkit/b", "project": "someone/other"},
                {"path": "/home/me/calkit/c", "project": project},
                {"path": "/home/me/misc"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    check_in = r.json()
    # Numbers that don't fit are refused
    for bad in [
        {"path": "/x", "ahead": -1},
        {"path": "/x", "behind": 2**31},
        {"path": "/x", "agents": [{"tool": "claude", "pid": 2**40}]},
    ]:
        r = client.post(
            "/machines/check-in",
            headers=op_headers,
            json={"workspaces": [bad]},
        )
        assert r.status_code == 422, bad
    assert check_in["relay_url"] == settings.relay_url
    payload = jwt.decode(
        check_in["relay_token"],
        settings.RELAY_SECRET_KEY,
        algorithms=["HS256"],
    )
    assert payload["scope"] == "relay:machine"
    assert payload["sub"] == op["id"]
    # Relay tokens can't be used on the API
    r = client.get(
        "/user",
        headers={"Authorization": f"Bearer {check_in['relay_token']}"},
    )
    assert r.status_code == 403
    r = client.get("/machines", headers=normal_user_token_headers)
    listed = {o["id"]: o for o in r.json()}
    assert listed[op["id"]]["is_online"]
    assert listed[op["id"]]["calkit_version"] == "1.2.3"
    assert listed[op["id"]]["workspace_count"] == 4
    assert "token" not in listed[op["id"]]
    # Its token is stored as a fast hash, since it's checked every minute
    machine = db.get(Machine, uuid.UUID(op["id"]))
    assert machine is not None
    assert len(machine.hashed_verifier) == 64
    hub_project = Project(
        name=f"on-hub-{uuid.uuid4().hex[:6]}",
        title="On the hub",
        git_repo_url="https://github.com/someone/on-hub",
        owner_account_id=user.account.id,
    )
    db.add(hub_project)
    su = db.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).one()
    private, public = [
        Project(
            name=f"{kind}-{uuid.uuid4().hex[:6]}",
            title=kind,
            git_repo_url=f"https://github.com/someone/{kind}",
            owner_account_id=su.account.id,
            is_public=kind == "public",
        )
        for kind in ["private", "public"]
    ]
    db.add(private)
    db.add(public)
    db.commit()
    # Checking in again updates workspaces in place, drops ones that are gone,
    # and reports runs in progress, which stages, and how the last run ended,
    # so the hub can show them without connecting
    last_run = {
        "status": "failed",
        "started": "2026-09-28T09:00:00+00:00",
        "ended": "2026-09-28T09:10:00+00:00",
        "failed_stages": ["plot"],
    }
    agent = {
        "tool": "claude",
        "pid": 123,
        "started": "2026-09-29T11:00:00+00:00",
        "where": "tmux",
        "app": "Terminal",
        "name": "Fix plots",
        "status": "busy",
    }
    r = client.post(
        "/machines/check-in",
        headers=op_headers,
        json={
            "workspaces": [
                {
                    "path": "/home/me/calkit/a",
                    "project": project,
                    "running": True,
                    "running_stages": ["train"],
                    "running_since": "2026-09-29T12:05:00+00:00",
                    "last_run": last_run,
                    "in_use_by": "http://localhost",
                    "last_activity": "2026-09-29T12:00:00+00:00",
                    "agents": [agent],
                },
                {"path": "/home/me/calkit/b", "project": "someone/other"},
                {
                    "path": "/home/me/calkit/d",
                    "project": f"{user.account.name}/{hub_project.name.upper()}",
                },
                # Another user's private project, which this one can't tell
                # exists, and a public one
                {
                    "path": "/home/me/calkit/e",
                    "project": f"{su.account.name}/{private.name}",
                },
                {
                    "path": "/home/me/calkit/f",
                    "project": f"{su.account.name}/{public.name}",
                },
                # A project that isn't named like one, and a path reported
                # twice, of which only the first counts
                {"path": "/home/me/misc", "project": "a/b/c"},
                {"path": "/home/me/misc", "project": "someone/else"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    # All of the user's workspaces are listed across machines, saying which
    # projects are on the hub
    r = client.get("/workspaces", headers=normal_user_token_headers)
    mine = [w for w in r.json() if w["machine_id"] == op["id"]]
    assert [w["path"] for w in mine] == [
        "/home/me/calkit/a",
        "/home/me/calkit/b",
        "/home/me/calkit/d",
        "/home/me/calkit/e",
        "/home/me/calkit/f",
        "/home/me/misc",
    ]
    assert [w["on_hub"] for w in mine] == [
        False,
        False,
        True,
        False,
        True,
        False,
    ]
    assert mine[0]["last_activity"] == "2026-09-29T12:00:00+00:00"
    assert mine[1]["last_activity"] is None
    # And which agents are running in them
    assert mine[0]["agents"] == [agent]
    assert mine[1]["agents"] == []
    assert mine[5]["project"] is None
    assert mine[0]["running"] and mine[0]["running_stages"] == ["train"]
    assert mine[0]["running_since"] == "2026-09-29T12:05:00+00:00"
    assert mine[0]["last_run"] == last_run
    assert mine[0]["in_use_by"] == "http://localhost"
    assert mine[1]["in_use_by"] is None
    assert mine[1]["running_stages"] == [] and mine[1]["last_run"] is None
    # Workspaces are listed per project, matched case-insensitively
    owner, name = project.split("/")
    r = client.get(
        f"/projects/{owner.upper()}/{name}/workspaces",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200, r.text
    workspaces = r.json()
    assert [w["path"] for w in workspaces] == ["/home/me/calkit/a"]
    assert workspaces[0]["project"] == project
    assert workspaces[0]["running"]
    assert workspaces[0]["machine_name"] == op["name"]
    assert workspaces[0]["machine_online"]
    assert workspaces[0]["machine_platform"] == "linux"
    # Other users see neither the machine nor its workspaces
    r = client.get(
        f"/projects/{owner}/{name}/workspaces", headers=superuser_token_headers
    )
    assert r.json() == []
    r = client.get("/workspaces", headers=superuser_token_headers)
    assert op["id"] not in [w["machine_id"] for w in r.json()]
    r = relay_token(superuser_token_headers, None)
    assert r.status_code == 404
    # Opening sessions takes two-factor authentication, set up and recent
    user = db.get(User, uuid.UUID(check_in["user_id"]))
    assert user is not None
    existing = db.get(UserTOTP, user.id)
    if existing is not None:
        db.delete(existing)
        db.commit()
    r = relay_token(normal_user_token_headers, None)
    assert r.status_code == 403
    assert r.json()["detail"] == SECOND_FACTOR_SETUP_REQUIRED
    # Once set up, a session needs its own proof of entering a code: the
    # account having entered one recently isn't enough
    totp = UserTOTP(
        user_id=user.id,
        secret=encrypt_secret(generate_totp_secret()),
        confirmed_at=utcnow() - timedelta(minutes=1),
        last_verified_at=utcnow(),
    )
    db.add(totp)
    db.commit()
    r = relay_token(normal_user_token_headers, None)
    assert r.status_code == 403
    assert r.json()["detail"] == SECOND_FACTOR_REQUIRED
    access_token = normal_user_token_headers["Authorization"].split()[1]
    session_id = uuid.UUID(
        jwt.decode(access_token, settings.SECRET_KEY, algorithms=["HS256"])[
            "sid"
        ]
    )
    second_factor = users.create_second_factor_token(user, session_id)
    # Another user's proof doesn't count, nor does the user's own from
    # another session
    for other in [
        create_second_factor_token(
            uuid.uuid4(), session_id, timedelta(hours=1)
        ),
        create_second_factor_token(user.id, uuid.uuid4(), timedelta(hours=1)),
    ]:
        r = relay_token(normal_user_token_headers, other)
        assert r.status_code == 403
    # Nor do logins that aren't a person signing in to the web app, e.g.,
    # the CLI's, a GitHub token's, or an emailed link's, even with proof
    cli_session_id = uuid.uuid4()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=uuid.uuid4().hex,
            expires=utcnow() + timedelta(days=1),
            session_id=cli_session_id,
        )
    )
    db.commit()
    for token in [
        create_access_token(
            user.id,
            timedelta(minutes=5),
            add_payload={"sid": str(cli_session_id)},
        ),
        create_access_token(user.id, timedelta(minutes=5)),
        generate_email_verification_token(user.id, user.email),
    ]:
        r = relay_token(
            {"Authorization": f"Bearer {token}"},
            create_second_factor_token(
                user.id, cli_session_id, timedelta(hours=1)
            ),
        )
        assert r.status_code == 403
    # Nor do tokens made for scripts, even with the proof
    r = client.post(
        "/user/tokens",
        headers=normal_user_token_headers,
        json={"expires_days": 1, "scope": None},
    )
    pat_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = relay_token(pat_headers, second_factor)
    assert r.status_code == 403
    # Browsers check the machine's replies with its key, so it has to have
    # sent one, which a machine installed over SSH does at its first
    # check-in, and which can't change after
    r = relay_token(normal_user_token_headers, second_factor)
    assert r.status_code == 409
    assert r.json()["detail"] == "Machine hasn't sent its key yet"
    for key, status in [
        (machine_jwk | {"y": machine_jwk["x"]}, 422),
        (machine_jwk, 200),
        (machine_jwk, 200),
        (make_jwk(), 409),
        (None, 200),
    ]:
        r = client.post(
            "/machines/check-in",
            headers=op_headers,
            json={
                "public_key": key,
                "workspaces": [
                    {"path": "/home/me/calkit/a", "project": project}
                ],
            },
        )
        assert r.status_code == status, r.text
    assert r.json()["grant_public_key"] == op["grant_public_key"]
    # Browsers get a short-lived relay token for an online machine, and
    # its key, which comes from the API, not the relay
    r = relay_token(normal_user_token_headers, second_factor)
    assert r.status_code == 200, r.text
    assert r.json()["machine_public_key"] == machine_jwk
    payload = jwt.decode(
        r.json()["token"], settings.RELAY_SECRET_KEY, algorithms=["HS256"]
    )
    assert payload["scope"] == "relay:browser"
    assert payload["sub"] == op["id"]
    # It carries a grant the API signed, which the machine checks against
    # the key the hub gives it at registration and check-in, so the relay
    # can't forge one
    public_key = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(op["grant_public_key"])
    )
    grant = jwt.decode(
        payload["grant"], public_key, algorithms=["EdDSA"], audience=op["id"]
    )
    assert grant["sub"] == str(user.id)
    assert check_in["grant_public_key"] == op["grant_public_key"]
    # The grant names the browser's key, so only messages it signs count,
    # and the sign-in, so the channel closes once that ends, as it does once
    # the second factor stops counting; its ID binds the machine's replies
    # to it
    assert grant["cnf"] == {"jwk": jwk}
    assert grant["sid"] == str(session_id)
    assert grant["jti"] == r.json()["grant_id"]
    assert (
        grant["tfa_exp"]
        == jwt.decode(second_factor, options={"verify_signature": False})[
            "exp"
        ]
    )
    assert abs(grant["iat"] - time.time()) < 10
    # A key that isn't on the curve, or isn't a key, is refused
    for bad in [
        jwk | {"y": jwk["x"]},
        jwk | {"crv": "P-384"},
        {"kty": "EC", "crv": "P-256", "x": "short", "y": jwk["y"]},
    ]:
        r = relay_token(
            normal_user_token_headers, second_factor, {"public_key": bad}
        )
        assert r.status_code == 422, bad
    # The machine fetches its own CLI token over HTTPS, never
    # sent through the relay, and only once its owner has asked for one,
    # within 10 minutes, with a second factor
    cli_token_request = f"/machines/{op['id']}/cli-token-request"
    r = client.post("/machines/cli-token", headers=op_headers)
    assert r.status_code == 403
    assert r.json()["detail"] == "No token was requested"
    for headers, factor in [
        (normal_user_token_headers, None),
        (pat_headers, second_factor),
        (superuser_token_headers, None),
    ]:
        client.cookies.clear()
        if factor is not None:
            client.cookies.set(users.SECOND_FACTOR_COOKIE, factor)
        r = client.post(cli_token_request, headers=headers)
        assert r.status_code in (403, 404), r.text
    r = client.post("/machines/cli-token", headers=op_headers)
    assert r.status_code == 403
    client.cookies.set(users.SECOND_FACTOR_COOKIE, second_factor)
    tokens = []
    for _ in range(2):
        r = client.post(cli_token_request, headers=normal_user_token_headers)
        assert r.status_code == 200, r.text
        r = client.post("/machines/cli-token", headers=op_headers)
        assert r.status_code == 200, r.text
        tokens.append(r.json()["token"])
        # Once
        r = client.post("/machines/cli-token", headers=op_headers)
        assert r.status_code == 403
    # It's a full token of the owner's, tied to the machine, and a new one
    # replaces the one before
    first, cli_token = tokens
    assert cli_token.startswith("ckp_")
    r = client.get("/user", headers={"Authorization": f"Bearer {cli_token}"})
    assert r.status_code == 200 and r.json()["id"] == str(user.id)
    r = client.get("/user", headers={"Authorization": f"Bearer {first}"})
    assert r.status_code == 403
    stored = db.exec(
        select(UserToken)
        .where(UserToken.machine_id == uuid.UUID(op["id"]))
        .where(UserToken.is_active)
    ).one()
    assert stored.description == f"Machine {op['name']}"
    # A request that's too old lapses
    r = client.post(cli_token_request, headers=normal_user_token_headers)
    machine = db.get(Machine, uuid.UUID(op["id"]))
    assert machine is not None
    db.refresh(machine)
    assert machine.cli_token_requested_at is not None
    machine.cli_token_requested_at -= timedelta(minutes=11)
    db.add(machine)
    db.commit()
    r = client.post("/machines/cli-token", headers=op_headers)
    assert r.status_code == 403
    # Sessions get credentials from the machine, which asks over HTTPS with
    # its own token and the grant that opened the session, even once that
    # has expired, so neither the relay, which carries grants, nor the
    # machine's token alone gets any
    session_grant = payload["grant"]
    session_token_url = "/machines/session-token"
    owner_id = user.id

    def grant_for(
        sign_in: uuid.UUID = session_id,
        machine_id: uuid.UUID = uuid.UUID(op["id"]),
        user_id: uuid.UUID = owner_id,
        tfa_exp: int | None = None,
    ) -> str:
        return create_machine_grant(
            machine_id,
            user_id,
            timedelta(seconds=-120),
            browser_key=jwk,
            session_id=sign_in,
            second_factor_expires=(
                int(time.time()) + 3600 if tfa_exp is None else tfa_exp
            ),
        )[0]

    r = client.post(
        session_token_url,
        headers=normal_user_token_headers,
        json={"grant": session_grant},
    )
    assert r.status_code == 403
    for bad in [
        "nope",
        grant_for(machine_id=uuid.uuid4()),
        grant_for(user_id=uuid.uuid4()),
        grant_for(sign_in=cli_session_id),
        grant_for(sign_in=uuid.uuid4()),
        grant_for(tfa_exp=int(time.time()) - 5),
    ]:
        r = client.post(
            session_token_url, headers=op_headers, json={"grant": bad}
        )
        assert r.status_code == 403, r.text
    r = client.post(
        session_token_url, headers=op_headers, json={"grant": grant_for()}
    )
    assert r.status_code == 200, r.text
    r = client.post(
        session_token_url, headers=op_headers, json={"grant": session_grant}
    )
    assert r.status_code == 200, r.text
    session_token = r.json()["token"]
    # It's the owner's, short-lived, and tied to the machine and sign-in
    claims = jwt.decode(
        session_token, settings.SECRET_KEY, algorithms=["HS256"]
    )
    assert claims["sub"] == str(user.id)
    assert claims["machine_id"] == op["id"]
    assert claims["link_sid"] == str(session_id)
    assert claims["exp"] - time.time() <= 15 * 60 + 5
    session_headers = {"Authorization": f"Bearer {session_token}"}
    r = client.get("/user", headers=session_headers)
    assert r.status_code == 200 and r.json()["id"] == str(user.id)
    # It can't make tokens that would outlive it, nor open sessions
    for scope in [None, "dvc"]:
        r = client.post(
            "/user/tokens",
            headers=session_headers,
            json={"expires_days": 1, "scope": scope},
        )
        assert r.status_code == 403, r.text
    r = relay_token(session_headers, second_factor)
    assert r.status_code == 403
    # Nor get the user's tokens for other services, which would too
    for path in [
        "/user/github-token",
        "/user/zenodo-token",
        "/user/overleaf-token",
    ]:
        r = client.get(path, headers=session_headers)
        assert r.status_code == 403, path
        assert r.json()["detail"] == "A hub session's token can't do this"
    # Nor does one come once the second factor is set up again
    confirmed = totp.confirmed_at
    totp.confirmed_at = utcnow() + timedelta(minutes=1)
    db.add(totp)
    db.commit()
    r = client.post(
        session_token_url, headers=op_headers, json={"grant": session_grant}
    )
    assert r.status_code == 403
    totp.confirmed_at = confirmed
    db.add(totp)
    db.commit()
    # Tokens stop working once their sign-in ends, and no more are issued
    ended_sign_in = uuid.uuid4()
    sign_in = RefreshToken(
        user_id=user.id,
        token_hash=uuid.uuid4().hex,
        expires=utcnow() + timedelta(days=1),
        session_id=ended_sign_in,
        interactive=True,
    )
    db.add(sign_in)
    db.commit()
    ended_grant = grant_for(sign_in=ended_sign_in)
    r = client.post(
        session_token_url, headers=op_headers, json={"grant": ended_grant}
    )
    ended_headers = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/user", headers=ended_headers).status_code == 200
    sign_in.is_active = False
    db.add(sign_in)
    db.commit()
    assert client.get("/user", headers=ended_headers).status_code == 403
    r = client.post(
        session_token_url, headers=op_headers, json={"grant": ended_grant}
    )
    assert r.status_code == 403
    # Git in sessions and actions gets the Calkit GitHub App's token for the
    # one repo it asks about, on the same terms, only for a project on the
    # hub the owner can access, and never the owner's own GitHub token,
    # which could be traded for a login. A hub project for a repo can be
    # made without any right to push to it, so the token is never more than
    # GitHub, or for an owner without GitHub, an invite, allows either
    gh_owner = f"me-{uuid.uuid4().hex[:6]}"
    hub_projects: dict[str, Project] = {}
    # However a project's URL writes the repo
    for name, git_repo_url, owner_id, is_public in [
        ("owned", "https://github.com/{}/Owned.git", user.account.id, False),
        (
            "http-form",
            "http://github.com/{}/http-form/",
            user.account.id,
            False,
        ),
        ("ssh-form", "git@github.com:{}/ssh-form.git", user.account.id, False),
        (
            "ssh-url-form",
            "ssh://git@github.com/{}/ssh-url-form",
            user.account.id,
            False,
        ),
        ("read", "https://github.com/{}/read", su.account.id, True),
        ("theirs", "https://github.com/{}/theirs", su.account.id, False),
        (
            "uninstalled",
            "https://github.com/{}/uninstalled",
            user.account.id,
            False,
        ),
        ("gone", "https://github.com/{}/gone", user.account.id, False),
        (
            "invited-write",
            "https://github.com/{}/invited-write",
            su.account.id,
            False,
        ),
        (
            "invited-read",
            "https://github.com/{}/invited-read",
            su.account.id,
            False,
        ),
        # Ones that only look like another's in SQL
        (
            "decoy-fork",
            "https://github.com/{}/decoy-fork",
            user.account.id,
            False,
        ),
        (
            "decoy-gitlab",
            "https://gitlab.com/github.com/{}/decoy",
            user.account.id,
            False,
        ),
    ]:
        made = Project(
            name=f"gh-{uuid.uuid4().hex[:8]}",
            title=name,
            git_repo_url=git_repo_url.format(
                gh_owner.upper() if name == "http-form" else gh_owner
            ),
            owner_account_id=owner_id,
            is_public=is_public,
        )
        db.add(made)
        hub_projects[name] = made
    db.commit()
    for name, role in [("invited-write", "write"), ("invited-read", "read")]:
        db.add(
            UserProjectAccess(
                user_id=user.id,
                project_id=hub_projects[name].id,
                role_id=ROLE_IDS[role],
            )
        )
    db.commit()
    minted: list[tuple[str, dict[str, str] | None]] = []

    def mint(
        owner: str,
        repo: str,
        read_only: bool = False,
        permissions: dict[str, str] | None = None,
    ) -> tuple[str, float]:
        assert owner == gh_owner
        if repo == "uninstalled":
            raise HTTPException(502, "GitHub returned 404")
        minted.append((repo, permissions))
        return "ghs_x", 2_000_000_000.5

    # What GitHub says the owner can do with each, asked with their token
    github_says: dict[str, Any] = {
        "owned": {"push": True, "pull": True},
        # A hub owner GitHub won't let push, which is the escalation this
        # guards against
        "http-form": {"push": False, "pull": True},
        "ssh-form": {"push": False, "pull": False},
        "ssh-url-form": TimeoutError,
        "read": {"push": False, "pull": True},
        "uninstalled": {"push": True, "pull": True},
        "gone": 404,
        "decoy-fork": None,
        "invited-write": {"push": True, "pull": True},
        "invited-read": {"push": True, "pull": True},
    }
    asked_github: list[str] = []

    def github_api(url: str, headers: dict[str, str], timeout: float) -> Any:
        import requests

        assert headers["Authorization"] == "Bearer gho_owner"
        repo = url.removeprefix(f"https://api.github.com/repos/{gh_owner}/")
        asked_github.append(repo)
        said = github_says.get(repo, 404)
        if said is TimeoutError:
            raise requests.Timeout("Timed out")
        resp = Mock(ok=said != 404)
        resp.json.return_value = {} if said is None else {"permissions": said}
        return resp

    def github_token(
        repo: str,
        shown: str = session_grant,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return client.post(
            "/machines/github-token",
            headers=headers or op_headers,
            json={"grant": shown, "owner": gh_owner, "repo": repo},
        )

    write, read = {"contents": "write"}, {"contents": "read"}
    Expected = list[tuple[str, dict[str, str] | None]]
    with (
        patch(
            "app.github.get_app_installation_token_and_expiry",
            side_effect=mint,
        ),
        patch("app.users.get_github_token", return_value="gho_owner"),
        patch("app.projects._resolve_github_collaborator_access"),
        patch("app.api.routes.machines.requests.get", side_effect=github_api),
    ):
        # Refused before anything's asked of GitHub
        for repo, shown, other_headers in [
            ("owned", ended_grant, None),
            ("owned", "nope", None),
            ("owned", session_grant, normal_user_token_headers),
            ("theirs", session_grant, None),
            ("elsewhere", session_grant, None),
            ("decoy", session_grant, None),
        ]:
            r = github_token(repo, shown, other_headers)
            assert r.status_code == 403, (repo, r.text)
        for bad in ["../x", "-x", "a b", "x/y", ""]:
            assert github_token(bad).status_code == 422
        assert asked_github == [] and minted == []
        # An owner with GitHub gets what it says, whatever the hub does
        github_name = user.account.github_name
        user.account.github_name = f"gh-{uuid.uuid4().hex[:6]}"
        db.add(user.account)
        db.commit()
        with_github: Expected = [
            ("owned", write),
            ("http-form", read),
            ("ssh-form", None),
            ("ssh-url-form", None),
            ("read", read),
            ("uninstalled", None),
            ("gone", None),
            ("decoy-fork", None),
            # GitHub's word, but no more than the hub's, which is "read"
            ("invited-read", read),
        ]
        for repo, expected in with_github:
            minted.clear()
            r = github_token(repo)
            if expected is None:
                assert r.status_code == 403, (repo, r.text)
                assert minted == []
            else:
                assert r.status_code == 200, (repo, r.text)
                assert r.json() == {"token": "ghs_x", "expires": 2_000_000_000}
                assert minted == [(repo, expected)]
                assert "gho_owner" not in r.text
        # One without GitHub gets what an invite gives, and nothing without
        user.account.github_name = None
        db.add(user.account)
        db.commit()
        asked_github.clear()
        without_github: Expected = [
            ("invited-write", write),
            ("invited-read", read),
            ("owned", None),
            ("read", None),
        ]
        for repo, expected in without_github:
            minted.clear()
            r = github_token(repo)
            if expected is None:
                assert r.status_code == 403, (repo, r.text)
                assert minted == []
            else:
                assert r.status_code == 200, (repo, r.text)
                assert minted == [(repo, expected)]
        assert asked_github == []
        user.account.github_name = github_name
        db.add(user.account)
        db.commit()
    # A machine that stopped checking in is offline
    machine.last_seen = utcnow() - timedelta(minutes=10)
    db.add(machine)
    db.commit()
    r = relay_token(normal_user_token_headers, second_factor)
    assert r.status_code == 409
    r = client.post(cli_token_request, headers=normal_user_token_headers)
    assert r.status_code == 409
    # A machine in cron mode that's between check-ins is asleep, and waking
    # it tells it to connect at its next check-in
    machine.mode = "cron"
    db.add(machine)
    db.commit()
    r = client.get("/machines", headers=normal_user_token_headers)
    listed = {o["id"]: o for o in r.json()}
    assert listed[op["id"]]["is_asleep"]
    assert not listed[op["id"]]["is_online"]
    r = client.get(
        f"/projects/{owner}/{name}/workspaces",
        headers=normal_user_token_headers,
    )
    assert r.json()[0]["machine_asleep"]
    r = client.post(
        f"/machines/{op['id']}/wake", headers=superuser_token_headers
    )
    assert r.status_code == 404
    # Checking in only to ask whether to connect doesn't make it online
    r = client.post(
        "/machines/check-in",
        headers=op_headers,
        json={"mode": "cron", "connected": False},
    )
    assert not r.json()["connect"]
    r = client.get("/machines", headers=normal_user_token_headers)
    listed = {o["id"]: o for o in r.json()}
    assert listed[op["id"]]["is_asleep"]
    assert not listed[op["id"]]["is_online"]
    r = client.post(
        f"/machines/{op['id']}/wake", headers=normal_user_token_headers
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/machines/check-in",
        headers=op_headers,
        json={"mode": "cron", "connected": False},
    )
    assert r.json()["connect"]
    # Once it has connected, the request is answered
    r = client.post(
        "/machines/check-in", headers=op_headers, json={"mode": "cron"}
    )
    r = client.post(
        "/machines/check-in",
        headers=op_headers,
        json={"mode": "cron", "connected": False},
    )
    assert not r.json()["connect"]
    # A restart is asked for once, and shows as pending until the machine
    # stops reporting it
    r = client.post(
        f"/machines/{op['id']}/restart", headers=superuser_token_headers
    )
    assert r.status_code == 404
    r = client.post(
        f"/machines/{op['id']}/restart", headers=normal_user_token_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["restart_pending"]
    for restart, reported in [(True, True), (False, True), (False, False)]:
        r = client.post(
            "/machines/check-in",
            headers=op_headers,
            json={"restart_pending": reported},
        )
        assert r.json()["restart"] == restart
        r = client.get("/machines", headers=normal_user_token_headers)
        listed = {o["id"]: o for o in r.json()}
        assert listed[op["id"]]["restart_pending"] == reported
    # Check-ins hear which of their channels' sign-ins have ended, e.g.,
    # with a password change, and only of the owner's
    other_session_id = uuid.uuid4()
    other_sign_in = RefreshToken(
        user_id=user.id,
        token_hash=uuid.uuid4().hex,
        expires=utcnow() + timedelta(days=1),
        session_id=other_session_id,
        interactive=True,
    )
    db.add(other_sign_in)
    db.commit()
    unknown = uuid.uuid4()

    def ended(*session_ids: uuid.UUID) -> set[str]:
        r = client.post(
            "/machines/check-in",
            headers=op_headers,
            json={"channel_sessions": [str(s) for s in session_ids]},
        )
        assert r.status_code == 200, r.text
        return set(r.json()["ended_sessions"])

    assert ended() == set()
    assert ended(session_id, other_session_id, unknown) == {str(unknown)}
    other_sign_in.is_active = False
    db.add(other_sign_in)
    db.commit()
    assert ended(session_id, other_session_id) == {str(other_session_id)}
    # Revoking takes a signed-in session, not a token, stops its token
    # working, deactivates the CLI token issued to its machine, and tells
    # the owner
    r = client.delete(f"/machines/{op['id']}", headers=pat_headers)
    assert r.status_code == 403
    with patch("app.api.routes.machines.send_email") as send:
        r = client.delete(
            f"/machines/{op['id']}", headers=normal_user_token_headers
        )
    assert r.status_code == 200
    assert send.call_args.kwargs["email_to"] == user.email
    assert "revoked" in send.call_args.kwargs["subject"]
    r = client.post("/machines/check-in", headers=op_headers, json={})
    assert r.status_code == 403
    assert "revoked" in r.json()["detail"]
    r = client.get("/user", headers={"Authorization": f"Bearer {cli_token}"})
    assert r.status_code == 403
    # As do its sessions' tokens
    assert client.get("/user", headers=session_headers).status_code == 403
    r = client.post(
        session_token_url, headers=op_headers, json={"grant": session_grant}
    )
    assert r.status_code == 403
    r = client.get("/machines", headers=normal_user_token_headers)
    assert op["id"] not in [o["id"] for o in r.json()]
    # A revoked machine's name can be used again
    r = client.post(
        "/machines",
        headers=normal_user_token_headers,
        json={"name": op["name"], "public_key": machine_jwk},
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == op["name"]
    # A machine can revoke itself, e.g., when it's unlinked, which
    # takes its CLI token with it too
    again = r.json()
    again_headers = {"Authorization": f"Bearer {again['token']}"}
    r = client.post(
        f"/machines/{again['id']}/cli-token-request",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 409
    r = client.post("/machines/check-in", headers=again_headers, json={})
    r = client.post(
        f"/machines/{again['id']}/cli-token-request",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200, r.text
    r = client.post("/machines/cli-token", headers=again_headers)
    again_cli = {"Authorization": f"Bearer {r.json()['token']}"}
    with patch("app.api.routes.machines.send_email"):
        r = client.delete("/machines/self", headers=again_headers)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == again["id"] and not r.json()["is_active"]
    r = client.post("/machines/check-in", headers=again_headers, json={})
    assert r.status_code == 403
    r = client.get("/machines/self", headers=again_headers)
    assert r.status_code == 403
    assert client.get("/user", headers=again_cli).status_code == 403
    client.cookies.clear()


def test_machine_owner_limits(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    from app.tests import (
        authentication_token_from_email,
        create_random_user,
    )

    user = create_random_user(db)
    user.email_verified_at = utcnow()
    db.add(user)
    db.commit()
    headers = authentication_token_from_email(
        client=client, email=user.email, db=db
    )
    r = client.post("/machines", headers=headers, json={"name": "first"})
    assert r.status_code == 200, r.text
    op_headers = {"Authorization": f"Bearer {r.json()['token']}"}
    # A user can only have so many active machines
    for n in range(49):
        db.add(
            Machine(
                user_id=user.id,
                name=f"op-{n}",
                selector=uuid.uuid4().hex,
                hashed_verifier=uuid.uuid4().hex,
            )
        )
    db.commit()
    r = client.post("/machines", headers=headers, json={"name": "another"})
    assert r.status_code == 409
    # Deactivating the owner revokes their machines, and ends every sign-in
    # their channels came from
    session_id = uuid.uuid4()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=uuid.uuid4().hex,
            expires=utcnow() + timedelta(days=1),
            session_id=session_id,
            interactive=True,
        )
    )
    db.commit()
    r = client.post(
        "/machines/check-in",
        headers=op_headers,
        json={"channel_sessions": [str(session_id)]},
    )
    assert r.json()["ended_sessions"] == []
    machine = db.exec(
        select(Machine)
        .where(Machine.user_id == user.id)
        .where(Machine.name == "first")
    ).one()
    user.is_active = False
    db.add(user)
    db.commit()
    from app.api.routes.machines import _ended_sessions

    db.refresh(machine)
    assert _ended_sessions(db, machine, [session_id]) == [session_id]
    r = client.post("/machines/check-in", headers=op_headers, json={})
    assert r.status_code == 403
    assert "revoked" in r.json()["detail"]


def test_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    import relay

    from app.security import create_relay_token

    monkeypatch.setenv("RELAY_SECRET_KEY", settings.RELAY_SECRET_KEY)
    machine_id = uuid.uuid4()
    user_id = uuid.uuid4()

    def token(
        kind: Literal["machine", "browser"],
        grant: str | None = None,
        user: uuid.UUID = user_id,
        machine: uuid.UUID = machine_id,
        seconds: int = 60,
    ) -> str:
        return create_relay_token(
            kind,
            machine_id=machine,
            user_id=user,
            expires_delta=timedelta(seconds=seconds),
            grant=grant,
        )

    @contextmanager
    def connect(client, path, tok):
        # Tokens go in the first message, not the URL, to stay out of logs
        with client.websocket_connect(path) as ws:
            ws.send_json({"type": "auth", "token": tok})
            yield ws

    with TestClient(relay.app) as client:
        # Bad tokens, tokens of the wrong kind, and used ones are refused
        used = token("browser")
        with pytest.raises(WebSocketDisconnect):
            with connect(client, "/browser", used) as ws:
                ws.receive_text()
        for path, tok in [
            ("/machine", "nope"),
            ("/machine", token("browser")),
            ("/browser", token("machine")),
            ("/browser", used),
        ]:
            with pytest.raises(WebSocketDisconnect) as e:
                with connect(client, path, tok) as ws:
                    ws.receive_text()
            assert e.value.code == relay.CLOSE_UNAUTHORIZED
        # Browsers can't connect to a machine that isn't connected
        with pytest.raises(WebSocketDisconnect) as e:
            with connect(client, "/browser", token("browser")) as ws:
                ws.receive_text()
        assert e.value.code == relay.CLOSE_MACHINE_OFFLINE
        with connect(client, "/machine", token("machine")) as op_ws:
            with connect(
                client, "/browser", token("browser", grant="signed")
            ) as browser_ws:
                opened = op_ws.receive_json()
                assert opened["type"] == "channel.open"
                assert opened["user_id"] == str(user_id)
                # The grant is passed along for the machine to check
                assert opened["grant"] == "signed"
                ch = opened["ch"]
                # Messages are wrapped on the way to the machine...
                browser_ws.send_json({"type": "sessions.list", "id": 1})
                assert op_ws.receive_json() == {
                    "type": "channel.message",
                    "ch": ch,
                    "msg": {"type": "sessions.list", "id": 1},
                }
                # ...and unwrapped on the way back
                op_ws.send_json({"ch": ch, "msg": {"type": "result", "id": 1}})
                assert browser_ws.receive_json() == {"type": "result", "id": 1}
                # Non-ASCII text goes as is, not escaped to take more room
                op_ws.send_json({"ch": ch, "msg": {"data": "é"}})
                assert browser_ws.receive_text() == '{"data":"é"}'
                # Messages over the limit close the connection, counted in
                # bytes rather than characters
                browser_ws.send_text("é" * (relay.MAX_MESSAGE_BYTES // 2 + 1))
                with pytest.raises(WebSocketDisconnect) as e:
                    browser_ws.receive_text()
                assert e.value.code == relay.CLOSE_TOO_BIG
            assert op_ws.receive_json() == {"type": "channel.close", "ch": ch}
            # The machine can close a channel, e.g., once its sign-in ends
            with connect(
                client, "/browser", token("browser", grant="signed")
            ) as browser_ws:
                ch = op_ws.receive_json()["ch"]
                op_ws.send_json({"type": "channel.close", "ch": ch})
                with pytest.raises(WebSocketDisconnect) as e:
                    browser_ws.receive_text()
                assert e.value.code == relay.CLOSE_UNAUTHORIZED
        # Health says nothing about who's connected
        assert client.get("/health").json() == {"ok": True}
        # A binary or oversized first message closes the connection, once
        big = "x" * (relay.MAX_MESSAGE_BYTES + 1)
        cases: list[tuple[str, bytes | str, int]] = [
            ("/machine", b"\0", relay.CLOSE_UNSUPPORTED),
            ("/browser", big, relay.CLOSE_TOO_BIG),
        ]
        for path, data, code in cases:
            with client.websocket_connect(path) as ws:
                if isinstance(data, bytes):
                    ws.send_bytes(data)
                else:
                    ws.send_text(data)
                with pytest.raises(WebSocketDisconnect) as e:
                    ws.receive_text()
            assert e.value.code == code
        # Too many connections waiting to send a token are turned away
        monkeypatch.setattr(relay, "MAX_UNAUTHENTICATED", 0)
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect("/machine") as ws:
                ws.receive_text()
        assert e.value.code == relay.CLOSE_TRY_AGAIN
        monkeypatch.undo()
        monkeypatch.setenv("RELAY_SECRET_KEY", settings.RELAY_SECRET_KEY)
        with connect(client, "/machine", token("machine")) as op_ws:
            # Browsers only reach their own user's machines
            stranger = token("browser", user=uuid.uuid4())
            with connect(client, "/browser", stranger) as browser_ws:
                with pytest.raises(WebSocketDisconnect) as e:
                    browser_ws.receive_text()
            assert e.value.code == relay.CLOSE_UNAUTHORIZED
        # A machine's connection closes once its token expires, unless it
        # sends a new one, which has to be for it
        with connect(client, "/machine", token("machine", seconds=2)) as op_ws:
            for bad in [
                "nope",
                token("browser"),
                token("machine", machine=uuid.uuid4()),
                token("machine", user=uuid.uuid4()),
            ]:
                op_ws.send_json({"type": "auth.refresh", "token": bad})
            refreshed = token("machine", seconds=60)
            op_ws.send_json({"type": "auth.refresh", "token": refreshed})
            time.sleep(2.5)
            with connect(client, "/browser", token("browser")):
                assert op_ws.receive_json()["type"] == "channel.open"
        with connect(client, "/machine", token("machine", seconds=1)) as op_ws:
            with pytest.raises(WebSocketDisconnect) as e:
                op_ws.receive_text()
            assert e.value.code == relay.CLOSE_UNAUTHORIZED
