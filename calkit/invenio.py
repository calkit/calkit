"""Functionality for working with InvenioRDM instances like Zenodo."""

import os
import time
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
            token = calkit.hub.get("/user/zenodo-token")["access_token"]
        return token
    elif service == "caltechdata":
        token = config.caltechdata_token
        if token is None:
            raise ValueError(f"No token for {service} found")
        return token
    else:
        raise ValueError(f"Unknown archival service '{service}'")


def get_base_url(service: ServiceName = DEFAULT_SERVICE) -> str:
    override = os.getenv(f"CALKIT_INVENIO_BASE_URL_{service.upper()}")
    if override:
        return override
    current_env = calkit.config.get_env()
    if service == "zenodo":
        if (
            current_env in ["local", "test"]
            and not os.getenv("CALKIT_USE_PROD_FOR_TESTS") == "1"
        ):
            return "https://sandbox.zenodo.org/api"
        return "https://zenodo.org/api"
    elif service == "caltechdata":
        if (
            current_env in ["local", "test"]
            and not os.getenv("CALKIT_USE_PROD_FOR_TESTS") == "1"
        ):
            return "https://data.caltechlibrary.dev/api"
        else:
            return "https://data.caltech.edu/api"
    else:
        raise ValueError(f"Unknown archival service '{service}'")


# Pushing a release can mean sending hundreds of megabytes over a slow or
# distant link, so give a response plenty of time to arrive rather than
# letting requests wait forever with no timeout at all.
CONNECT_TIMEOUT = 30
READ_TIMEOUT = 600
# Gateways in front of InvenioRDM return these when they're busy, which says
# nothing about whether the request itself was valid, so it's worth sending
# again after a pause.
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4


def get_timeout() -> tuple[float, float]:
    """Get the connect and read timeouts to use for requests."""
    read = os.getenv("CALKIT_INVENIO_TIMEOUT")
    return CONNECT_TIMEOUT, float(read) if read else READ_TIMEOUT


def _request(
    kind: Literal["get", "post", "put", "patch", "delete"],
    path: str,
    params: dict | None = None,
    json: dict | list | None = None,
    data: dict | bytes | None = None,
    headers: dict | None = None,
    auth: bool = True,
    as_json: bool = True,
    service: ServiceName = DEFAULT_SERVICE,
    **kwargs,
):
    if params is None:
        params = {}
    if auth and "access_token" not in params:
        params = params | {"access_token": get_token(service=service)}
    kwargs.setdefault("timeout", get_timeout())
    func = getattr(requests, kind)
    # A POST that timed out may still have been carried out on the far end,
    # e.g., leaving a draft record behind, so only repeat requests that are
    # safe to send twice
    max_attempts = 1 if kind == "post" else MAX_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        try:
            resp = func(
                get_base_url(service=service) + path,
                params=params,
                json=json,
                data=data,
                headers=headers,
                **kwargs,
            )
        except (requests.ConnectionError, requests.Timeout):
            if attempt == max_attempts:
                raise
            time.sleep(2**attempt)
            continue
        if resp.status_code in RETRY_STATUS_CODES and attempt < max_attempts:
            time.sleep(2**attempt)
            continue
        break
    if resp.status_code >= 400:
        msg = f"{resp.status_code}: "
        try:
            resp_json = resp.json()
            if "message" in resp_json:
                msg += resp_json["message"]
            if "errors" in resp_json:
                msg += f"\nErrors:\n{resp_json['errors']}"
        except ValueError:
            msg += resp.text
        if kind == "post" and resp.status_code in RETRY_STATUS_CODES:
            # The far end may have done the work anyway, and a blind retry
            # would duplicate it, so say so rather than papering over it
            msg += (
                f"\nThis request was not retried automatically, since "
                f"{service} may have carried it out despite the error. "
                "Check for a leftover draft record before trying again."
            )
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


def extract_doi(record: dict) -> str | None:
    """Extract the DOI identifier from an InvenioRDM record or response.

    Depending on the endpoint and whether the DOI has been minted yet, the
    identifier can live in different places, so check all known locations and
    return ``None`` if it isn't present yet.
    """
    pids = record.get("pids")
    if isinstance(pids, dict):
        doi = pids.get("doi")
        if isinstance(doi, dict) and doi.get("identifier"):
            return doi["identifier"]
    if record.get("doi"):
        return record["doi"]
    metadata = record.get("metadata")
    if isinstance(metadata, dict) and metadata.get("doi"):
        return metadata["doi"]
    return None


def get_download_urls(
    record_id: int | str,
    service: ServiceName = DEFAULT_SERVICE,
    auth: bool = True,
) -> dict[str, str]:
    resp = get(f"/records/{record_id}", service=service, auth=auth)
    download_urls = [f["links"]["self"] for f in resp["files"]]
    filenames = [f["key"] for f in resp["files"]]
    urls = {}
    for fname, url in zip(filenames, download_urls):
        urls[fname] = url
    return urls
