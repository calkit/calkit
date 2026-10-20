"""The relay: pairs browsers with machines over websockets.

It runs as one process, separate from the API, so both ends of a pairing
meet in memory. It has no database and trusts only relay tokens the API
signed, so the only setting it needs is ``RELAY_SECRET_KEY``, which can't
sign logins. It lives outside
the ``app`` package because importing that loads the API's settings,
which require all of its secrets.
See docs/dev/hub-link-protocol.md.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Literal

import jwt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MAX_MESSAGE_BYTES = 256 * 1024
# How long a new connection has to send its token
AUTH_TIMEOUT_SECONDS = 10
# How many connections may be waiting to send one at once
MAX_UNAUTHENTICATED = 200
METER_LOG_INTERVAL_SECONDS = 60
# Close codes
CLOSE_UNSUPPORTED = 1003
CLOSE_TOO_BIG = 1009
CLOSE_TRY_AGAIN = 1013
CLOSE_UNAUTHORIZED = 4401
CLOSE_MACHINE_OFFLINE = 4404
CLOSE_REPLACED = 4409
CLOSE_MACHINE_GONE = 4410


def decode_relay_token(
    token: str, kind: Literal["machine", "browser"]
) -> dict | None:
    """Decode a relay token, returning None if it's invalid or expired."""
    try:
        payload = jwt.decode(
            token, os.environ["RELAY_SECRET_KEY"], algorithms=["HS256"]
        )
    except jwt.InvalidTokenError:
        return None
    if payload.get("scope") != f"relay:{kind}":
        return None
    # Each token opens one connection, so one copied from somewhere is
    # worthless once it has
    jti = payload.get("jti")
    now = time.time()
    for used, exp in list(used_tokens.items()):
        if exp < now:
            del used_tokens[used]
    if not isinstance(jti, str) or jti in used_tokens:
        return None
    used_tokens[jti] = float(payload["exp"])
    return payload


class Closed(Exception):
    """The relay closed a socket itself, so it mustn't close it again."""


async def authenticate(
    ws: WebSocket, kind: Literal["machine", "browser"]
) -> dict | None:
    """Accept a connection and take its token from its first message.

    Tokens go in a message rather than the URL, so they stay out of
    access logs.
    """
    global unauthenticated
    if unauthenticated >= MAX_UNAUTHENTICATED:
        await ws.close(CLOSE_TRY_AGAIN)
        return None
    unauthenticated += 1
    try:
        await ws.accept()
        async with asyncio.timeout(AUTH_TIMEOUT_SECONDS):
            msg = await _receive(ws)
    except (WebSocketDisconnect, Closed):
        return None
    except TimeoutError:
        msg = {}
    finally:
        unauthenticated -= 1
    token = msg.get("token")
    payload = (
        decode_relay_token(token, kind) if isinstance(token, str) else None
    )
    if payload is None:
        await ws.close(CLOSE_UNAUTHORIZED)
    return payload


class Machine:
    def __init__(self, ws: WebSocket, user_id: str, exp: float) -> None:
        self.ws = ws
        self.user_id = user_id
        # When its token expires, which refreshing it pushes back
        self.exp = exp
        self.channels: dict[str, WebSocket] = {}


machines: dict[str, Machine] = {}
# Connections that haven't sent a token yet
unauthenticated = 0
# IDs of relay tokens already used, with when they expire
used_tokens: dict[str, float] = {}
# Bytes relayed per machine since the last log, as (to machine, from it)
meter: dict[str, list[int]] = defaultdict(lambda: [0, 0])


async def log_meter() -> None:
    while True:
        await asyncio.sleep(METER_LOG_INTERVAL_SECONDS)
        for machine_id, (to_op, from_op) in list(meter.items()):
            logger.info(
                f"Relayed for machine {machine_id}: "
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
    return {"ok": True}


async def _receive(ws: WebSocket) -> dict:
    """Receive one JSON message, closing the socket if it's too big or
    binary, which raises Closed.
    """
    message = await ws.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    text = message.get("text")
    if text is None:
        await ws.close(CLOSE_UNSUPPORTED)
        raise Closed
    if len(text.encode()) > MAX_MESSAGE_BYTES:
        await ws.close(CLOSE_TOO_BIG)
        raise Closed
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


@app.websocket("/machine")
async def machine_ws(ws: WebSocket) -> None:
    payload = await authenticate(ws, "machine")
    if payload is None:
        return
    machine_id = payload["sub"]
    existing = machines.get(machine_id)
    if existing is not None:
        try:
            await existing.ws.close(CLOSE_REPLACED)
        except Exception:
            pass
    machine = Machine(
        ws, user_id=payload["user_id"], exp=float(payload["exp"])
    )
    machines[machine_id] = machine
    logger.info(f"Machine {machine_id} connected")
    loop = asyncio.get_running_loop()
    try:
        while True:
            # Its token has to be refreshed before it expires, which it is
            # after each check-in, so one revoked, or taken by someone who
            # can't check in, doesn't stay connected
            deadline = loop.time() + machine.exp - time.time()
            try:
                async with asyncio.timeout_at(deadline):
                    msg = await _receive(ws)
            except TimeoutError:
                logger.info(f"Machine {machine_id}'s token expired")
                await ws.close(CLOSE_UNAUTHORIZED)
                break
            if msg.get("type") == "auth.refresh":
                token = msg.get("token")
                refreshed = (
                    decode_relay_token(token, "machine")
                    if isinstance(token, str)
                    else None
                )
                if (
                    refreshed is None
                    or refreshed.get("sub") != machine_id
                    or refreshed.get("user_id") != machine.user_id
                ):
                    logger.info(f"Machine {machine_id} sent a bad refresh")
                    continue
                machine.exp = float(refreshed["exp"])
                continue
            ch = msg.get("ch")
            if not isinstance(ch, str):
                continue
            browser = machine.channels.get(ch)
            if browser is None:
                continue
            # The machine closed it, e.g., because its sign-in ended
            if msg.get("type") == "channel.close":
                machine.channels.pop(ch, None)
                try:
                    await browser.close(CLOSE_UNAUTHORIZED)
                except Exception:
                    pass
                continue
            if "msg" not in msg:
                continue
            meter[machine_id][1] += await _send(browser, msg["msg"])
    except (WebSocketDisconnect, Closed):
        pass
    finally:
        # A replaced connection must not tear down its replacement
        if machines.get(machine_id) is machine:
            del machines[machine_id]
        for browser in list(machine.channels.values()):
            try:
                await browser.close(CLOSE_MACHINE_GONE)
            except Exception:
                pass
        logger.info(f"Machine {machine_id} disconnected")


@app.websocket("/browser")
async def browser_ws(ws: WebSocket) -> None:
    payload = await authenticate(ws, "browser")
    if payload is None:
        return
    machine_id = payload["sub"]
    machine = machines.get(machine_id)
    if machine is None:
        await ws.close(CLOSE_MACHINE_OFFLINE)
        return
    # Only its owner can reach it
    if payload.get("user_id") != machine.user_id:
        await ws.close(CLOSE_UNAUTHORIZED)
        return
    ch = uuid.uuid4().hex[:12]
    machine.channels[ch] = ws
    meter[machine_id][0] += await _send(
        machine.ws,
        {
            "type": "channel.open",
            "ch": ch,
            "user_id": payload["user_id"],
            # Signed by the API for the machine to check, since it doesn't
            # take the relay's word for who opened the channel
            "grant": payload.get("grant"),
        },
    )
    try:
        while True:
            msg = await _receive(ws)
            # The machine may have reconnected since this browser did
            if machines.get(machine_id) is not machine:
                await ws.close(CLOSE_MACHINE_GONE)
                break
            meter[machine_id][0] += await _send(
                machine.ws, {"type": "channel.message", "ch": ch, "msg": msg}
            )
    except (WebSocketDisconnect, Closed):
        pass
    finally:
        machine.channels.pop(ch, None)
        if machines.get(machine_id) is machine:
            await _send(machine.ws, {"type": "channel.close", "ch": ch})
