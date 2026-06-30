"""The Calkit Operator.

This is a process that runs in the background, connected to a Calkit
cloud, and allows connecting to workspaces running on the operator's system
to do things like run pipeline stages, read files, or even start processes
like the VS Code server.
"""

from __future__ import annotations

import asyncio
from typing import Literal

import websockets
from pydantic import BaseModel


class Message(BaseModel):
    pass


class StartCodeServer(Message):
    kind: Literal["start-code-server"] = "start-code-server"
    wdir: str


class RunPipelineStage(Message):
    kind: Literal["run-pipeline-stage"] = "run-pipeline-stage"
    wdir: str
    stage_name: str


class Ls(Message):
    kind: Literal["ls"] = "ls"


class Connect(Message):
    kind: Literal["connect"] = "connect"


async def listen_to_server():
    uri = "ws://localhost:8765"  # Replace with your WebSocket URI
    async with websockets.connect(uri) as websocket:
        await websocket.send(Connect().model_dump_json())
        while True:
            try:
                message = await websocket.recv()
                # TODO: Figure out what kind of message this is
                print(f"Received: {message}")
            except websockets.ConnectionClosed:
                break


def main():
    asyncio.run(listen_to_server())
