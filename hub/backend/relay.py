"""The relay: pairs browsers with Operators over websockets.

It runs as one process, separate from the API, so both ends of a pairing
meet in memory. It has no database and trusts only relay tokens the API
signed, so the only setting it needs is ``SECRET_KEY``. It lives outside
the ``app`` package because importing that loads the API's settings,
which require all of its secrets.
See docs/dev/operator-protocol.md.
"""

import asyncio
import json
import logging
import os
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Literal

import jwt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MAX_MESSAGE_BYTES = 256 * 1024
METER_LOG_INTERVAL_SECONDS = 60
# Close codes
CLOSE_TOO_BIG = 1009
CLOSE_UNAUTHORIZED = 4401
CLOSE_OPERATOR_OFFLINE = 4404
CLOSE_REPLACED = 4409
CLOSE_OPERATOR_GONE = 4410


def decode_relay_token(
    token: str, kind: Literal["operator", "browser"]
) -> dict | None:
    """Decode a relay token, returning None if it's invalid or expired."""
    try:
        payload = jwt.decode(
            token, os.environ["SECRET_KEY"], algorithms=["HS256"]
        )
    except jwt.InvalidTokenError:
        return None
    if payload.get("scope") != f"relay:{kind}":
        return None
    return payload


class Operator:
    def __init__(self, ws: WebSocket, user_id: str) -> None:
        self.ws = ws
        self.user_id = user_id
        self.channels: dict[str, WebSocket] = {}


operators: dict[str, Operator] = {}
# Bytes relayed per Operator since the last log, as (to Operator, from it)
meter: dict[str, list[int]] = defaultdict(lambda: [0, 0])


async def log_meter() -> None:
    while True:
        await asyncio.sleep(METER_LOG_INTERVAL_SECONDS)
        for operator_id, (to_op, from_op) in list(meter.items()):
            logger.info(
                f"Relayed for Operator {operator_id}: "
                f"{to_op} B to, {from_op} B from"
            )
        meter.clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(log_meter())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan, openapi_url=None)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "operators": len(operators)}


async def _receive(ws: WebSocket) -> dict | None:
    """Receive one JSON message, closing the socket if it's too big."""
    text = await ws.receive_text()
    if len(text) > MAX_MESSAGE_BYTES:
        await ws.close(CLOSE_TOO_BIG)
        return None
    try:
        msg = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return msg if isinstance(msg, dict) else {}


async def _send(ws: WebSocket, msg: dict) -> int:
    text = json.dumps(msg, separators=(",", ":"))
    try:
        await ws.send_text(text)
    except Exception:
        # The other end went away; its own handler cleans up
        return 0
    return len(text)


@app.websocket("/operator")
async def operator_ws(ws: WebSocket, token: str) -> None:
    payload = decode_relay_token(token, "operator")
    if payload is None:
        await ws.close(CLOSE_UNAUTHORIZED)
        return
    await ws.accept()
    operator_id = payload["sub"]
    existing = operators.get(operator_id)
    if existing is not None:
        await existing.ws.close(CLOSE_REPLACED)
    operator = Operator(ws, user_id=payload["user_id"])
    operators[operator_id] = operator
    logger.info(f"Operator {operator_id} connected")
    try:
        while True:
            msg = await _receive(ws)
            if msg is None:
                break
            ch = msg.get("ch")
            browser = (
                operator.channels.get(ch) if isinstance(ch, str) else None
            )
            if browser is None or "msg" not in msg:
                continue
            meter[operator_id][1] += await _send(browser, msg["msg"])
    except WebSocketDisconnect:
        pass
    finally:
        # A replaced connection must not tear down its replacement
        if operators.get(operator_id) is operator:
            del operators[operator_id]
        for browser in list(operator.channels.values()):
            try:
                await browser.close(CLOSE_OPERATOR_GONE)
            except Exception:
                pass
        logger.info(f"Operator {operator_id} disconnected")


@app.websocket("/browser")
async def browser_ws(ws: WebSocket, token: str) -> None:
    payload = decode_relay_token(token, "browser")
    if payload is None:
        await ws.close(CLOSE_UNAUTHORIZED)
        return
    operator_id = payload["sub"]
    operator = operators.get(operator_id)
    if operator is None:
        await ws.close(CLOSE_OPERATOR_OFFLINE)
        return
    await ws.accept()
    ch = uuid.uuid4().hex[:12]
    operator.channels[ch] = ws
    meter[operator_id][0] += await _send(
        operator.ws,
        {"type": "channel.open", "ch": ch, "user_id": payload["user_id"]},
    )
    try:
        while True:
            msg = await _receive(ws)
            if msg is None:
                break
            # The Operator may have reconnected since this browser did
            if operators.get(operator_id) is not operator:
                await ws.close(CLOSE_OPERATOR_GONE)
                break
            meter[operator_id][0] += await _send(
                operator.ws, {"type": "channel.message", "ch": ch, "msg": msg}
            )
    except WebSocketDisconnect:
        pass
    finally:
        operator.channels.pop(ch, None)
        if operators.get(operator_id) is operator:
            await _send(operator.ws, {"type": "channel.close", "ch": ch})
