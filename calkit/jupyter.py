"""Functionality for working with Jupyter."""

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


def start_server():
    """Start a Jupyter server in the current directory.

    TODO: Set the origins appropriately for running from the main Calkit
    website.
    """
    subprocess.Popen(
        [
            "jupyter",
            "lab",
            "-y",
            "--no-browser",
            "--NotebookApp.allow_origin='http://localhost:*'",
            (
                "--NotebookApp.tornado_settings="
                "{'headers':{'Access-Control-Allow-Origin'"
                ":'http://localhost:*',"
                "'Content-Security-Policy'"
                ":'frame-ancestors http://localhost:*;'}}"
            ),
        ]
    )
