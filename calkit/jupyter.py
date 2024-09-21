"""Functionality for working with Jupyter."""

import subprocess

from pydantic import BaseModel

import calkit


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


def start_server(wdir=None):
    """Start a Jupyter server.

    TODO: Set the origins appropriately for running from the main Calkit
    website.
    """
    origins = dict(
        local="http://localhost:*",
        production="https://calkit.io",
        staging="https://staging.calkit.io",
    )
    allow_origin = origins[calkit.config.get_env()]
    subprocess.Popen(
        [
            "jupyter",
            "lab",
            "-y",
            "--no-browser",
            f"--ServerApp.allow_origin='{allow_origin}'",
            (
                "--ServerApp.tornado_settings="
                "{'headers':{'Access-Control-Allow-Origin'"
                f":'{allow_origin}',"
                "'Content-Security-Policy'"
                f":'frame-ancestors {allow_origin};'}}}}"
            ),
        ],
        cwd=wdir,
    )
