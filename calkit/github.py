"""Functionality for working with GitHub."""

import os
from functools import partial
from typing import Literal

import dotenv
import requests
from requests.exceptions import HTTPError

import calkit


def get_token() -> str:
    dotenv.load_dotenv()
    token = calkit.config.read().github_token
    if token is None:
        token = os.getenv("GITHUB_TOKEN")
    if token is None:
        token = calkit.hub.get("/user/github-token")["access_token"]
    return token


def get_base_url() -> str:
    return "https://api.github.com"


def _request(
    kind: Literal["get", "post", "put", "patch", "delete"],
    path: str,
    params: dict | None = None,
    json: dict | None = None,
    data: dict | None = None,
    headers: dict | None = None,
    as_json=True,
    **kwargs,
):
    if headers is None:
        headers = {}
    if "Authorization" not in headers:
        headers = headers | {"Authorization": f"Bearer {get_token()}"}
    func = getattr(requests, kind)
    resp = func(
        get_base_url() + path,
        params=params,
        json=json,
        data=data,
        headers=headers,
        **kwargs,
    )
    if resp.status_code >= 400:
        resp_json = resp.json()
        msg = f"{resp.status_code}: "
        if "message" in resp_json:
            msg += resp_json["message"]
        if "errors" in resp_json:
            msg += f"\nErrors:\n{resp_json['errors']}"
        raise HTTPError(msg)
    resp.raise_for_status()
    if as_json:
        return resp.json()
    else:
        return resp


get = partial(_request, "get")
post = partial(_request, "post")
patch = partial(_request, "patch")
put = partial(_request, "put")
delete = partial(_request, "delete")


def can_use_ssh(interactive: bool = False) -> bool:
    """Whether Git can reach GitHub over SSH, i.e., there's a key GitHub
    accepts.

    Unless ``interactive``, nothing is asked, e.g., to trust GitHub's host
    key or for a key's passphrase, so an SSH setup that would need either
    counts as not set up.
    """
    import subprocess

    cmd = ["ssh", "-T", "-o", "ConnectTimeout=5"]
    if not interactive:
        cmd += ["-o", "BatchMode=yes"]
    try:
        p = subprocess.run(
            [*cmd, "git@github.com"],
            capture_output=True,
            text=True,
            timeout=None if interactive else 15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    # GitHub greets an accepted key, then exits with 1 since it gives no
    # shell
    return "successfully authenticated" in p.stdout + p.stderr
