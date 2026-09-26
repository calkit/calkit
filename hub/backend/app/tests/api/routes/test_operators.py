import uuid
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.core import utcnow
from app.models import Operator


def test_operators(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    hostname = f"Lab-Box-{uuid.uuid4().hex[:6]}"
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
                {"path": "/home/me/calkit/a", "project": project},
                {"path": "/home/me/calkit/b", "project": "someone/other"},
                {"path": "/home/me/misc"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    check_in = r.json()
    assert check_in["relay_url"] == settings.relay_url
    payload = jwt.decode(
        check_in["relay_token"], settings.SECRET_KEY, algorithms=["HS256"]
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
    assert "token" not in listed[op["id"]]
    # Workspaces are listed per project, matched case-insensitively
    owner, name = project.split("/")
    r = client.get(
        f"/projects/{owner.upper()}/{name}/workspaces",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200, r.text
    workspaces = r.json()
    assert [w["path"] for w in workspaces] == ["/home/me/calkit/a"]
    assert workspaces[0]["operator_name"] == op["name"]
    assert workspaces[0]["operator_online"]
    assert workspaces[0]["operator_platform"] == "linux"
    # Other users see neither the Operator nor its workspaces
    r = client.get(
        f"/projects/{owner}/{name}/workspaces", headers=superuser_token_headers
    )
    assert r.json() == []
    r = client.post(
        f"/operators/{op['id']}/relay-token", headers=superuser_token_headers
    )
    assert r.status_code == 404
    # Browsers get a short-lived relay token for an online Operator
    r = client.post(
        f"/operators/{op['id']}/relay-token", headers=normal_user_token_headers
    )
    assert r.status_code == 200, r.text
    payload = jwt.decode(
        r.json()["token"], settings.SECRET_KEY, algorithms=["HS256"]
    )
    assert payload["scope"] == "relay:browser"
    assert payload["sub"] == op["id"]
    # An Operator that stopped checking in is offline
    operator = db.get(Operator, uuid.UUID(op["id"]))
    assert operator is not None
    operator.last_seen = utcnow() - timedelta(minutes=10)
    db.add(operator)
    db.commit()
    r = client.post(
        f"/operators/{op['id']}/relay-token", headers=normal_user_token_headers
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


def test_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    import relay

    from app.security import create_relay_token

    monkeypatch.setenv("SECRET_KEY", settings.SECRET_KEY)
    operator_id = uuid.uuid4()
    user_id = uuid.uuid4()

    def token(kind):
        return create_relay_token(
            kind,
            operator_id=operator_id,
            user_id=user_id,
            expires_delta=timedelta(minutes=1),
        )

    with TestClient(relay.app) as client:
        # Bad tokens, and tokens of the wrong kind, are refused
        for path, tok in [
            ("/operator", "nope"),
            ("/operator", token("browser")),
            ("/browser", token("operator")),
        ]:
            with pytest.raises(WebSocketDisconnect) as e:
                with client.websocket_connect(f"{path}?token={tok}") as ws:
                    ws.receive_text()
            assert e.value.code == relay.CLOSE_UNAUTHORIZED
        # Browsers can't connect to an Operator that isn't connected
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect(
                f"/browser?token={token('browser')}"
            ) as ws:
                ws.receive_text()
        assert e.value.code == relay.CLOSE_OPERATOR_OFFLINE
        with client.websocket_connect(
            f"/operator?token={token('operator')}"
        ) as op_ws:
            with client.websocket_connect(
                f"/browser?token={token('browser')}"
            ) as browser_ws:
                opened = op_ws.receive_json()
                assert opened["type"] == "channel.open"
                assert opened["user_id"] == str(user_id)
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
