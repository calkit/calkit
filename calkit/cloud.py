"""The REST API client."""

from __future__ import annotations

import time
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
        "test": "http://api.localhost",
    }
    return urls[config.get_env()]


def get_token() -> str:
    """Get a token.

    Automatically load from config when not cached.
    """
    token = _tokens.get(get_base_url())
    if token is None:
        token = config.read().token
        _tokens[get_base_url()] = token
    # TODO: Check for expiration
    if token is None:
        raise ValueError(
            "No token found; Run 'calkit cloud login' to authenticate"
        )
    return token


def get_headers(headers: dict | None = None, auth: bool = True) -> dict:
    if auth:
        base_headers = {"Authorization": f"Bearer {get_token()}"}
    else:
        base_headers = {}
    if headers is not None:
        return base_headers | headers
    else:
        return base_headers


def _request(
    kind: Literal["get", "post", "put", "patch", "delete"],
    path: str,
    params: dict | None = None,
    json: dict | None = None,
    data: dict | None = None,
    headers: dict | None = None,
    as_json=True,
    auth: bool = True,
    base_url: str | None = None,
    **kwargs,
):
    max_retries = 10
    base_delay_seconds = 0.25
    max_delay_seconds = 30
    func = getattr(requests, kind)
    if base_url is None:
        base_url = get_base_url()
    for retry_num in range(max_retries + 1):
        resp = func(
            base_url + path,
            params=params,
            json=json,
            data=data,
            headers=get_headers(headers, auth=auth),
            **kwargs,
        )
        if resp.status_code == 502 and retry_num < max_retries:
            wait = min(base_delay_seconds * (2**retry_num), max_delay_seconds)
            time.sleep(wait)
            continue
        try:
            resp.raise_for_status()
        except HTTPError as e:
            try:
                detail = resp.json()["detail"]
            except Exception:
                raise e
            raise HTTPError(f"{resp.status_code}: {detail}")
        break
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
