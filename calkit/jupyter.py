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
    subprocess.Popen(
        [
            "jupyter",
            "lab",
            "-y",
            "--no-browser",
            "--NotebookApp.allow_origin='*'",
            (
                "--NotebookApp.tornado_settings="
                "{'headers':{'Access-Control-Allow-Origin':'*',"
                "'Content-Security-Policy':'frame-ancestors *;'}}"
            ),
        ]
    )
