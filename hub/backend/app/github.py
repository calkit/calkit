"""GitHub related functionality."""

import os
import threading
import time
from datetime import datetime

import jwt
import requests
from fastapi import HTTPException

from app.config import settings


class GitHubAppNotConfigured(Exception):
    """Raised when the GitHub App private key isn't available."""


def _load_app_signing_key() -> bytes:
    """Return the GitHub App private key (PEM) from settings.

    Raises GitHubAppNotConfigured if GH_APP_PRIVATE_KEY isn't set.
    """
    if not settings.GH_APP_PRIVATE_KEY:
        raise GitHubAppNotConfigured(
            "GitHub App private key not configured (set GH_APP_PRIVATE_KEY)"
        )
    # Env vars commonly carry the PEM with escaped newlines; restore them so
    # the key parses whether it was provided escaped or as a real multi-line.
    return settings.GH_APP_PRIVATE_KEY.replace("\\n", "\n").encode()


def create_app_token() -> str:
    client_id = os.environ["GH_CLIENT_ID"]
    signing_key = _load_app_signing_key()
    payload = {
        # Issued at time
        "iat": int(time.time()),
        # JWT expiration time (10 minutes maximum)
        "exp": int(time.time()) + 600,
        # GitHub App's client ID
        "iss": client_id,
    }
    # Create JWT
    encoded_jwt = jwt.encode(payload, signing_key, algorithm="RS256")
    return encoded_jwt


# Cache of GitHub App installation tokens, keyed by (owner, repo) -> (token,
# expiry_epoch). Installation tokens are valid ~1 hour; reusing them until just
# before expiry means a GitHub-less user's request doesn't mint a fresh token
# (two GitHub API calls) on every repo operation. This is a per-worker
# in-process cache, so each worker mints at most once per repo per ~hour.
_installation_token_cache: dict[tuple[str, str], tuple[str, float]] = {}
_installation_token_cache_lock = threading.Lock()
# Refresh this long before GitHub's stated expiry so a cached token can't lapse
# mid-request.
_INSTALLATION_TOKEN_SAFETY_SECONDS = 300


def get_app_installation_token(owner_name: str, repo_name: str) -> str:
    """Return a GitHub App installation access token scoped to one repo.

    Used to perform git operations on behalf of users who have native Calkit
    access to a project but no personal GitHub token (e.g. email/Google
    signups). Tokens are cached in-process and reused until shortly before they
    expire. The caller must have authorized the user's access first.
    """
    cache_key = (owner_name.lower(), repo_name.lower())
    now = time.time()
    with _installation_token_cache_lock:
        cached = _installation_token_cache.get(cache_key)
        if cached is not None and cached[1] > now:
            return cached[0]
    # Miss or expired: mint a fresh token. Done outside the lock so requests
    # for different repos don't serialize; a rare concurrent double-mint just
    # yields two valid tokens.
    token, expires_at = _mint_app_installation_token(owner_name, repo_name)
    # ~50 min fallback if GitHub omits expires_at for some reason.
    expiry = now + 3000.0
    if expires_at:
        try:
            parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            expiry = parsed.timestamp() - _INSTALLATION_TOKEN_SAFETY_SECONDS
        except ValueError:
            pass
    with _installation_token_cache_lock:
        _installation_token_cache[cache_key] = (token, expiry)
    return token


def _mint_app_installation_token(
    owner_name: str, repo_name: str
) -> tuple[str, str | None]:
    """Mint a fresh installation token, returning (token, expires_at)."""
    app_jwt = create_app_token()
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.get(
        f"https://api.github.com/repos/{owner_name}/{repo_name}/installation",
        headers=headers,
        timeout=15,
    )
    if resp.status_code != 200:
        # Include GitHub's status and message so real causes are visible: a
        # 401 ("could not be decoded") means GH_APP_PRIVATE_KEY doesn't match
        # the App for GH_CLIENT_ID; a 404 means the App isn't installed on the
        # repo. Reporting a bare "installation not found" hides the difference.
        raise HTTPException(
            502,
            "Could not look up the Calkit GitHub App installation for "
            f"{owner_name}/{repo_name}: GitHub returned {resp.status_code} "
            f"({resp.text[:200]})",
        )
    installation_id = resp.json()["id"]
    resp = requests.post(
        f"https://api.github.com/app/installations/{installation_id}"
        "/access_tokens",
        headers=headers,
        json={"repositories": [repo_name]},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise HTTPException(
            502,
            "Could not mint a Calkit GitHub App installation token for "
            f"{owner_name}/{repo_name}: GitHub returned {resp.status_code} "
            f"({resp.text[:200]})",
        )
    data = resp.json()
    return data["token"], data.get("expires_at")


def token_resp_text_to_dict(resp_text: str) -> dict:
    items = resp_text.split("&")
    out = {}
    for item in items:
        key, value = item.split("=")
        out[key] = value
    return out
