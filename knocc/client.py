"""The REST API client."""

import requests

from . import config

# A dictionary of tokens keyed by base URL
_tokens = {}


def get_base_url() -> str:
    """Get the API base URL.

    TODO: Use production, but respect env variable.
    """
    return "http://localhost"


def get_token() -> str:
    """Get a token.

    Automatically reauthenticate if the token doesn't exist or has expired.
    """
    token = _tokens.get(get_base_url())
    # TODO: Check for expiration
    if token is None:
        return auth()


def auth() -> str:
    """Authenticate with the server and save a token."""
    cfg = config.read()
    base_url = get_base_url()
    resp = requests.post(
        base_url + "/login/access-token",
        data=dict(username=cfg["username"], password=cfg["password"]),
    )
    token = resp.json()["access_token"]
    _tokens[base_url] = token
    return token
