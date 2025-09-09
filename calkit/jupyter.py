"""Functionality for working with Jupyter."""

from __future__ import annotations

import subprocess

from pydantic import BaseModel


class Server(BaseModel):
    url: str
    wdir: str
    token: str


def get_servers() -> list[Server]:
    out = (
        subprocess.check_output(["jupyter", "server", "list"])
        .decode()
        .strip()
        .split("\n")
    )
    resp = []
    for line in out:
        if line.startswith("http://"):
            url, wdir = line.split(" :: ")
            token = url.split("?token=")[-1]
            resp.append(Server(url=url, wdir=wdir, token=token))
    return resp


def start_server(wdir=None, no_browser=False):
    """Start a Jupyter server."""
    subprocess.Popen(
        [
            "jupyter",
            "lab",
            "-y",
            "--no-browser" if no_browser else "",
        ],
        cwd=wdir,
    )


def stop_server(url: str):
    # Extract the port from the URL
    port = url.split(":")[2][:4]
    subprocess.call(["jupyter", "server", "stop", port])
