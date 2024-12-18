"""Working with DVC."""

from __future__ import annotations

import logging
import os
import subprocess

import calkit
from calkit.config import get_app_name

logger = logging.getLogger(__package__)
logger.setLevel(logging.INFO)


def configure_remote(wdir: str = None):
    project_name = calkit.git.detect_project_name(path=wdir)
    base_url = calkit.cloud.get_base_url()
    remote_url = f"{base_url}/projects/{project_name}/dvc"
    subprocess.check_call(
        ["dvc", "remote", "add", "-d", "-f", get_app_name(), remote_url],
        cwd=wdir,
    )
    subprocess.check_call(
        ["dvc", "remote", "modify", get_app_name(), "auth", "custom"],
        cwd=wdir,
    )


def set_remote_auth(
    remote_name: str = None, always_auth: bool = False, wdir: str = None
):
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
    subprocess.check_call(
        [
            "dvc",
            "remote",
            "modify",
            "--local",
            remote_name,
            "custom_auth_header",
            "Authorization",
        ],
        cwd=wdir,
    )
    subprocess.check_call(
        [
            "dvc",
            "remote",
            "modify",
            "--local",
            remote_name,
            "password",
            f"Bearer {settings.dvc_token}",
        ],
        cwd=wdir,
    )


def add_external_remote(owner_name: str, project_name: str):
    base_url = calkit.cloud.get_base_url()
    remote_url = f"{base_url}/projects/{owner_name}/{project_name}/dvc"
    remote_name = f"{get_app_name()}:{owner_name}/{project_name}"
    subprocess.call(["dvc", "remote", "add", "-f", remote_name, remote_url])
    subprocess.call(["dvc", "remote", "modify", remote_name, "auth", "custom"])
    set_remote_auth(remote_name)


def read_pipeline(wdir: str = ".") -> dict:
    fpath = os.path.join(wdir, "dvc.yaml")
    if not os.path.isfile(fpath):
        return {}
    with open(fpath) as f:
        return calkit.ryaml.load(f)


def get_remotes(wdir: str = None) -> dict[str, str]:
    """Get a dictionary of DVC remotes, keyed by name, with URL as the
    value.
    """
    out = (
        subprocess.check_output(["dvc", "remote", "list"], cwd=wdir)
        .decode()
        .strip()
    )
    if not out:
        return {}
    resp = {}
    for line in out.split("\n"):
        name, url = line.split("\t")
        resp[name] = url
    return resp
