"""Functionality for working with Zenodo."""

import os
from functools import partial
from typing import Literal

import dotenv
import requests
from requests.exceptions import HTTPError

import calkit


def get_token() -> str:
    dotenv.load_dotenv()
    token = calkit.config.read().zenodo_token
    if token is None:
        token = os.getenv("ZENODO_TOKEN")
    if token is None:
        token = calkit.cloud.get("/user/zenodo-token")["access_token"]
    return token


def get_base_url() -> str:
    if calkit.config.get_env() == "local":
        return "https://sandbox.zenodo.org/api"
    return "https://zenodo.org/api"


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
    if params is None:
        params = {}
    if "access_token" not in params:
        params = params | {"access_token": get_token()}
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


def get_download_urls(record_id: int) -> dict[str, str]:
    resp = get(f"/records/{record_id}")
    download_urls = [f["links"]["self"] for f in resp["files"]]
    filenames = [f["key"] for f in resp["files"]]
    urls = {}
    for fname, url in zip(filenames, download_urls):
        urls[fname] = url
    return urls
