"""The REST API client."""

import os

import requests

from . import config

# A dictionary of tokens keyed by base URL
_tokens = {}


def get_base_url() -> str:
    """Get the API base URL.

    TODO: Use production, but respect env variable.
    """
    urls = {"local": "http://localhost/api/v1", "prod": "TODO"}
    default_env = "local"
    return urls[os.getenv(__package__.upper() + "_ENV") or default_env]


def get_token() -> str:
    """Get a token.

    Automatically reauthenticate if the token doesn't exist or has expired.
    """
    token = _tokens.get(get_base_url())
    # TODO: Check for expiration
    if token is None:
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
    base_url = get_base_url()
    resp = requests.post(
        base_url + "/login/access-token",
        data=dict(username=cfg.username, password=cfg.password),
    )
    token = resp.json()["access_token"]
    _tokens[base_url] = token
    return token


def get(
    path: str,
    params: dict | None = None,
    json: dict | None = None,
    data: dict | None = None,
    headers: dict | None = None,
    as_json=True,
    **kwargs,
):
    resp = requests.get(
        get_base_url() + path,
        params=params,
        json=json,
        data=data,
        headers=get_headers(headers),
        **kwargs,
    )
    resp.raise_for_status()
    if as_json:
        return resp.json()
    else:
        return resp


def get_current_user() -> dict:
    return get("/users/me")
