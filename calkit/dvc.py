"""Working with DVC."""

from __future__ import annotations

import logging
import os
import subprocess

import calkit
from calkit.config import get_app_name

logger = logging.getLogger(__package__)
logger.setLevel(logging.INFO)


def configure_remote():
    project_name = calkit.git.detect_project_name()
    base_url = calkit.cloud.get_base_url()
    remote_url = f"{base_url}/projects/{project_name}/dvc"
    subprocess.call(
        ["dvc", "remote", "add", "-d", "-f", get_app_name(), remote_url]
    )
    subprocess.call(
        ["dvc", "remote", "modify", get_app_name(), "auth", "custom"]
    )


def set_remote_auth(remote_name: str = None, always_auth: bool = False):
    """Get a token and set it in the local DVC config so we can interact with
    the cloud as an HTTP remote.
    """
    if remote_name is None:
        remote_name = get_app_name()
    settings = calkit.config.read()
    if settings.dvc_token is None or always_auth:
        logger.info("Creating token for DVC scope")
        token = calkit.cloud.post(
            "/user/tokens", json=dict(expires_days=365, scope="dvc")
        )["access_token"]
        settings.dvc_token = token
        settings.write()
    subprocess.call(
        [
            "dvc",
            "remote",
            "modify",
            "--local",
            remote_name,
            "custom_auth_header",
            "Authorization",
        ]
    )
    subprocess.call(
        [
            "dvc",
            "remote",
            "modify",
            "--local",
            remote_name,
            "password",
            f"Bearer {settings.dvc_token}",
        ]
    )


def add_external_remote(owner_name: str, project_name: str):
    base_url = calkit.cloud.get_base_url()
    remote_url = f"{base_url}/projects/{owner_name}/{project_name}/dvc"
    remote_name = f"{get_app_name()}:{owner_name}/{project_name}"
    subprocess.call(["dvc", "remote", "add", "-f", remote_name, remote_url])
    subprocess.call(["dvc", "remote", "modify", remote_name, "auth", "custom"])
    set_remote_auth(remote_name)


def read_pipeline() -> dict:
    if not os.path.isfile("dvc.yaml"):
        return {}
    with open("dvc.yaml") as f:
        return calkit.ryaml.load(f)


def get_remotes() -> dict[str, str]:
    """Get a dictionary of DVC remotes, keyed by name, with URL as the
    value.
    """
    out = subprocess.check_output(["dvc", "remote", "list"]).decode().strip()
    if not out:
        return {}
    resp = {}
    for line in out.split("\n"):
        name, url = line.split("\t")
        resp[name] = url
    return resp
