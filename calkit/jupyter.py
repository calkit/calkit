"""Functionality for working with Jupyter."""

from __future__ import annotations

import os
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


def check_path():
    """Ensure that the Jupyter environment can access Calkit resources when
    installed in a uv tool environment.
    """
    tool_share = os.path.join(
        os.path.expanduser("~"),
        ".local",
        "share",
        "uv",
        "tools",
        "calkit-python",
        "share",
        "jupyter",
    )
    if os.path.isdir(tool_share):
        # Prepend to JUPYTER_PATH so that Jupyter can find
        # Calkit resources (kernelspecs, nbextensions, labextensions, etc)
        jupyter_path = os.environ.get("JUPYTER_PATH", "")
        if tool_share not in jupyter_path.split(":"):
            os.environ["JUPYTER_PATH"] = f"{tool_share}:{jupyter_path}"
