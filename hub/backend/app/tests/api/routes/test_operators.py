import base64
import uuid
from contextlib import contextmanager
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi.testclient import TestClient
from sqlmodel import Session
from starlette.websockets import WebSocketDisconnect

from app import users
from app.config import settings
from app.core import utcnow
from app.models import Operator, RefreshToken, User, UserTOTP
from app.security import (
    create_access_token,
    create_second_factor_token,
    encrypt_secret,
    generate_email_verification_token,
    generate_totp_secret,
)
from app.users import SECOND_FACTOR_REQUIRED, SECOND_FACTOR_SETUP_REQUIRED


def test_operators(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    hostname = f"Lab-Box-{uuid.uuid4().hex[:6]}"
    # Registering takes a verified email, since that's what setting up the
    # second factor for opening sessions proves itself with
    me = client.get("/user", headers=normal_user_token_headers).json()
    user = db.get(User, uuid.UUID(me["id"]))
    assert user is not None
    user.email_verified_at = None
    db.add(user)
    db.commit()
    r = client.post(
        "/operators",
        headers=normal_user_token_headers,
        json={"hostname": hostname},
    )
    assert r.status_code == 403
    user.email_verified_at = utcnow()
    db.add(user)
    db.commit()
    # Names default to the slugified hostname, suffixed until unique
    r = client.post(
        "/operators",
        headers=normal_user_token_headers,
        json={"hostname": hostname, "platform": "linux"},
    )
    assert r.status_code == 200, r.text
    op = r.json()
    assert op["name"] == hostname.lower()
    assert op["hosts"] == [hostname]
    assert op["token"].startswith("cko_")
    assert not op["is_online"]
    op_headers = {"Authorization": f"Bearer {op['token']}"}
    r = client.post(
        "/operators",
        headers=normal_user_token_headers,
        json={"hostname": hostname},
    )
    assert r.json()["name"] == f"{hostname.lower()}-2"
    # An explicit name that's taken is refused rather than suffixed
    r = client.post(
        "/operators",
        headers=normal_user_token_headers,
        json={"name": op["name"]},
    )
    assert r.status_code == 409
    # Operator tokens only work for Operator routes, and vice versa
    assert client.get("/user", headers=op_headers).status_code == 403
    r = client.post(
        "/operators/check-in", headers=normal_user_token_headers, json={}
    )
    assert r.status_code == 403
    # Check in with workspaces from two projects
    project = f"someone/proj-{uuid.uuid4().hex[:6]}"
    r = client.post(
        "/operators/check-in",
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
    assert check_in["relay_url"] == settings.relay_url
    payload = jwt.decode(
        check_in["relay_token"],
        settings.RELAY_SECRET_KEY,
        algorithms=["HS256"],
    )
    assert payload["scope"] == "relay:operator"
    assert payload["sub"] == op["id"]
    # Relay tokens can't be used on the API
    r = client.get(
        "/user",
        headers={"Authorization": f"Bearer {check_in['relay_token']}"},
    )
    assert r.status_code == 403
    r = client.get("/operators", headers=normal_user_token_headers)
    listed = {o["id"]: o for o in r.json()}
    assert listed[op["id"]]["is_online"]
    assert listed[op["id"]]["calkit_version"] == "1.2.3"
    assert listed[op["id"]]["workspace_count"] == 4
    assert "token" not in listed[op["id"]]
    # Its token is stored as a fast hash, since it's checked every minute
    operator = db.get(Operator, uuid.UUID(op["id"]))
    assert operator is not None
    assert len(operator.hashed_verifier) == 64
    # Checking in again updates workspaces in place, drops ones that are gone,
    # and reports runs in progress, which stages, and how the last run ended,
    # so the hub can show them without connecting
    last_run = {
        "status": "failed",
        "started": "2026-09-28T09:00:00+00:00",
        "ended": "2026-09-28T09:10:00+00:00",
        "failed_stages": ["plot"],
    }
    r = client.post(
        "/operators/check-in",
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
                },
                {"path": "/home/me/calkit/b", "project": "someone/other"},
                {"path": "/home/me/misc"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    # All of the user's workspaces are listed across Operators
    r = client.get("/workspaces", headers=normal_user_token_headers)
    mine = [w for w in r.json() if w["operator_id"] == op["id"]]
    assert [w["path"] for w in mine] == [
        "/home/me/calkit/a",
        "/home/me/calkit/b",
        "/home/me/misc",
    ]
    assert mine[2]["project"] is None
    assert mine[0]["running"] and mine[0]["running_stages"] == ["train"]
    assert mine[0]["running_since"] == "2026-09-29T12:05:00+00:00"
    assert mine[0]["last_run"] == last_run
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
    assert workspaces[0]["operator_name"] == op["name"]
    assert workspaces[0]["operator_online"]
    assert workspaces[0]["operator_platform"] == "linux"
    # Other users see neither the Operator nor its workspaces
    r = client.get(
        f"/projects/{owner}/{name}/workspaces", headers=superuser_token_headers
    )
    assert r.json() == []
    r = client.get("/workspaces", headers=superuser_token_headers)
    assert op["id"] not in [w["operator_id"] for w in r.json()]
    r = client.post(
        f"/operators/{op['id']}/relay-token", headers=superuser_token_headers
    )
    assert r.status_code == 404
    # Opening sessions takes two-factor authentication, set up and recent
    user = db.get(User, uuid.UUID(check_in["user_id"]))
    existing = db.get(UserTOTP, user.id)
    if existing is not None:
        db.delete(existing)
        db.commit()
    r = client.post(
        f"/operators/{op['id']}/relay-token", headers=normal_user_token_headers
    )
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
    r = client.post(
        f"/operators/{op['id']}/relay-token", headers=normal_user_token_headers
    )
    assert r.status_code == 403
    assert r.json()["detail"] == SECOND_FACTOR_REQUIRED
    access_token = normal_user_token_headers["Authorization"].split()[1]
    session_id = uuid.UUID(
        jwt.decode(access_token, settings.SECRET_KEY, algorithms=["HS256"])[
            "sid"
        ]
    )
    second_factor = users.create_second_factor_token(user, session_id)
    with_second_factor = normal_user_token_headers | {
        "X-Second-Factor": second_factor
    }
    # Another user's proof doesn't count, nor does the user's own from
    # another session
    for other in [
        create_second_factor_token(
            uuid.uuid4(), session_id, timedelta(hours=1)
        ),
        create_second_factor_token(user.id, uuid.uuid4(), timedelta(hours=1)),
    ]:
        r = client.post(
            f"/operators/{op['id']}/relay-token",
            headers=normal_user_token_headers | {"X-Second-Factor": other},
        )
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
        r = client.post(
            f"/operators/{op['id']}/relay-token",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Second-Factor": create_second_factor_token(
                    user.id, cli_session_id, timedelta(hours=1)
                ),
            },
        )
        assert r.status_code == 403
    # Nor do tokens made for scripts, even with the proof
    r = client.post(
        "/user/tokens",
        headers=normal_user_token_headers,
        json={"expires_days": 1, "scope": None},
    )
    pat_headers = {
        "Authorization": f"Bearer {r.json()['access_token']}",
        "X-Second-Factor": second_factor,
    }
    r = client.post(f"/operators/{op['id']}/relay-token", headers=pat_headers)
    assert r.status_code == 403
    # Browsers get a short-lived relay token for an online Operator
    r = client.post(
        f"/operators/{op['id']}/relay-token", headers=with_second_factor
    )
    assert r.status_code == 200, r.text
    payload = jwt.decode(
        r.json()["token"], settings.RELAY_SECRET_KEY, algorithms=["HS256"]
    )
    assert payload["scope"] == "relay:browser"
    assert payload["sub"] == op["id"]
    # It carries a grant the API signed, which the Operator checks against
    # the key it pinned when it registered, so the relay can't forge one
    public_key = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(op["grant_public_key"])
    )
    grant = jwt.decode(
        payload["grant"], public_key, algorithms=["EdDSA"], audience=op["id"]
    )
    assert grant["sub"] == str(user.id)
    assert check_in["grant_public_key"] == op["grant_public_key"]
    # An Operator that stopped checking in is offline
    operator = db.get(Operator, uuid.UUID(op["id"]))
    assert operator is not None
    operator.last_seen = utcnow() - timedelta(minutes=10)
    db.add(operator)
    db.commit()
    r = client.post(
        f"/operators/{op['id']}/relay-token", headers=with_second_factor
    )
    assert r.status_code == 409
    # An Operator in cron mode that's between check-ins is asleep, and waking
    # it tells it to connect at its next check-in
    operator.mode = "cron"
    db.add(operator)
    db.commit()
    r = client.get("/operators", headers=normal_user_token_headers)
    listed = {o["id"]: o for o in r.json()}
    assert listed[op["id"]]["is_asleep"]
    assert not listed[op["id"]]["is_online"]
    r = client.get(
        f"/projects/{owner}/{name}/workspaces",
        headers=normal_user_token_headers,
    )
    assert r.json()[0]["operator_asleep"]
    r = client.post(
        f"/operators/{op['id']}/wake", headers=superuser_token_headers
    )
    assert r.status_code == 404
    # Checking in only to ask whether to connect doesn't make it online
    r = client.post(
        "/operators/check-in",
        headers=op_headers,
        json={"mode": "cron", "connected": False},
    )
    assert not r.json()["connect"]
    r = client.get("/operators", headers=normal_user_token_headers)
    listed = {o["id"]: o for o in r.json()}
    assert listed[op["id"]]["is_asleep"]
    assert not listed[op["id"]]["is_online"]
    r = client.post(
        f"/operators/{op['id']}/wake", headers=normal_user_token_headers
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/operators/check-in",
        headers=op_headers,
        json={"mode": "cron", "connected": False},
    )
    assert r.json()["connect"]
    # Once it has connected, the request is answered
    r = client.post(
        "/operators/check-in", headers=op_headers, json={"mode": "cron"}
    )
    r = client.post(
        "/operators/check-in",
        headers=op_headers,
        json={"mode": "cron", "connected": False},
    )
    assert not r.json()["connect"]
    # Revoking stops its token working
    r = client.delete(
        f"/operators/{op['id']}", headers=normal_user_token_headers
    )
    assert r.status_code == 200
    r = client.post("/operators/check-in", headers=op_headers, json={})
    assert r.status_code == 403
    assert "revoked" in r.json()["detail"]
    r = client.get("/operators", headers=normal_user_token_headers)
    assert op["id"] not in [o["id"] for o in r.json()]
    # A revoked Operator's name can be used again
    r = client.post(
        "/operators",
        headers=normal_user_token_headers,
        json={"name": op["name"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == op["name"]


def test_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    import relay

    from app.security import create_relay_token

    monkeypatch.setenv("RELAY_SECRET_KEY", settings.RELAY_SECRET_KEY)
    operator_id = uuid.uuid4()
    user_id = uuid.uuid4()

    def token(kind, grant=None):
        return create_relay_token(
            kind,
            operator_id=operator_id,
            user_id=user_id,
            expires_delta=timedelta(minutes=1),
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
            ("/operator", "nope"),
            ("/operator", token("browser")),
            ("/browser", token("operator")),
            ("/browser", used),
        ]:
            with pytest.raises(WebSocketDisconnect) as e:
                with connect(client, path, tok) as ws:
                    ws.receive_text()
            assert e.value.code == relay.CLOSE_UNAUTHORIZED
        # Browsers can't connect to an Operator that isn't connected
        with pytest.raises(WebSocketDisconnect) as e:
            with connect(client, "/browser", token("browser")) as ws:
                ws.receive_text()
        assert e.value.code == relay.CLOSE_OPERATOR_OFFLINE
        with connect(client, "/operator", token("operator")) as op_ws:
            with connect(
                client, "/browser", token("browser", grant="signed")
            ) as browser_ws:
                opened = op_ws.receive_json()
                assert opened["type"] == "channel.open"
                assert opened["user_id"] == str(user_id)
                # The grant is passed along for the Operator to check
                assert opened["grant"] == "signed"
                ch = opened["ch"]
                # Messages are wrapped on the way to the Operator...
                browser_ws.send_json({"type": "sessions.list", "id": 1})
                assert op_ws.receive_json() == {
                    "type": "channel.message",
                    "ch": ch,
                    "msg": {"type": "sessions.list", "id": 1},
                }
                # ...and unwrapped on the way back
                op_ws.send_json({"ch": ch, "msg": {"type": "result", "id": 1}})
                assert browser_ws.receive_json() == {"type": "result", "id": 1}
                # Messages over the limit close the connection
                browser_ws.send_text("x" * (relay.MAX_MESSAGE_BYTES + 1))
                with pytest.raises(WebSocketDisconnect) as e:
                    browser_ws.receive_text()
                assert e.value.code == relay.CLOSE_TOO_BIG
            assert op_ws.receive_json() == {"type": "channel.close", "ch": ch}
