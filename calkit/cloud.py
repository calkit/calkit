"""The REST API client."""

from __future__ import annotations

import warnings
from functools import partial
from typing import Literal

import requests
from requests.exceptions import HTTPError

from . import config

# A dictionary of tokens keyed by base URL
_tokens = {}


def get_base_url() -> str:
    """Get the API base URL."""
    urls = {
        "local": "http://api.localhost",
        "staging": "https://api.staging.calkit.io",
        "production": "https://api.calkit.io",
    }
    return urls[config.get_env()]


def get_token() -> str:
    """Get a token.

    Automatically reauthenticate if the token doesn't exist or has expired.
    """
    token = _tokens.get(get_base_url())
    if token is None:
        token = config.read().token
        _tokens[get_base_url()] = token
    # TODO: Check for expiration
    if token is None:
        warnings.warn("No token found; attempting email+password auth")
        return auth()
    return token


def get_headers(headers: dict | None = None) -> dict:
    base_headers = {"Authorization": f"Bearer {get_token()}"}
    if headers is not None:
        return base_headers | headers
    else:
        return base_headers


def auth() -> str:
    """Authenticate with the server and save a token."""
    cfg = config.read()
    if cfg.email is None or cfg.password is None:
        raise ValueError("Config is missing email or password")
    base_url = get_base_url()
    resp = requests.post(
        base_url + "/login/access-token",
        data=dict(username=cfg.email, password=cfg.password),
    )
    token = resp.json()["access_token"]
    _tokens[base_url] = token
    return token


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
    func = getattr(requests, kind)
    resp = func(
        get_base_url() + path,
        params=params,
        json=json,
        data=data,
        headers=get_headers(headers),
        **kwargs,
    )
    try:
        resp.raise_for_status()
    except HTTPError as e:
        try:
            detail = resp.json()["detail"]
        except Exception:
            raise e
        raise HTTPError(f"{resp.status_code}: {detail}")
    if as_json:
        return resp.json()
    else:
        return resp


get = partial(_request, "get")
post = partial(_request, "post")
patch = partial(_request, "patch")
put = partial(_request, "put")
delete = partial(_request, "delete")


def get_current_user() -> dict:
    return get("/user")
