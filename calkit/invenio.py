"""Functionality for working with InvenioRDM instances like Zenodo."""

import os
from functools import partial
from typing import Literal

import dotenv
import requests
from requests.exceptions import HTTPError

import calkit

ServiceName = Literal["zenodo", "caltechdata"]
DEFAULT_SERVICE = "zenodo"


def get_token(service: ServiceName = DEFAULT_SERVICE) -> str:
    dotenv.load_dotenv()
    config = calkit.config.read()
    if service == "zenodo":
        token = config.zenodo_token
        if token is None:
            token = os.getenv("ZENODO_TOKEN")
        if token is None:
            token = calkit.cloud.get("/user/zenodo-token")["access_token"]
        return token
    elif service == "caltechdata":
        token = config.caltechdata_token
        if token is None:
            raise ValueError(f"No token for {service} found")
    else:
        raise ValueError(f"Unknown archival service '{service}'")
    return token


def get_base_url(service: ServiceName = DEFAULT_SERVICE) -> str:
    current_env = calkit.config.get_env()
    if service == "zenodo":
        if current_env in ["local", "test"]:
            return "https://sandbox.zenodo.org/api"
        return "https://zenodo.org/api"
    elif service == "caltechdata":
        if current_env in ["local", "test"]:
            return "https://data.caltechlibrary.dev/api"
        else:
            return "https://data.caltech.edu/api"


def _request(
    kind: Literal["get", "post", "put", "patch", "delete"],
    path: str,
    params: dict | None = None,
    json: dict | list | None = None,
    data: dict | bytes | None = None,
    headers: dict | None = None,
    as_json: bool = True,
    service: ServiceName = DEFAULT_SERVICE,
    **kwargs,
):
    if params is None:
        params = {}
    if "access_token" not in params:
        params = params | {"access_token": get_token(service=service)}
    func = getattr(requests, kind)
    resp = func(
        get_base_url(service=service) + path,
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


def get_download_urls(
    record_id: int | str, service: ServiceName = DEFAULT_SERVICE
) -> dict[str, str]:
    resp = get(f"/records/{record_id}", service=service)
    download_urls = [f["links"]["self"] for f in resp["files"]]
    filenames = [f["key"] for f in resp["files"]]
    urls = {}
    for fname, url in zip(filenames, download_urls):
        urls[fname] = url
    return urls
