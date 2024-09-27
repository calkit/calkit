"""Working with DVC."""

from __future__ import annotations

import logging
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


def set_remote_auth():
    """Get a token and set it in the local DVC config so we can interact with
    the cloud as an HTTP remote.
    """
    settings = calkit.config.read()
    if settings.dvc_token is None:
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
            get_app_name(),
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
            get_app_name(),
            "password",
            f"Bearer {settings.dvc_token}",
        ]
    )
