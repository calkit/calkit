"""Working with DVC."""

import subprocess

import calkit
from calkit.config import get_app_name


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
    """Get a token and set it in the local config so we can interact with
    the API.
    """
    token = calkit.cloud.post(
        "/user/tokens", json=dict(expires_days=365, scope="dvc")
    )["access_token"]
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
            f"Bearer {token}",
        ]
    )
