"""Working with DVC."""

import subprocess

import calkit

REMOTE_NAME = "local"  # TODO: Use package name


def configure_remote():
    project_name = calkit.git.detect_project_name()
    base_url = calkit.get_base_url()
    remote_url = f"{base_url}/projects/{project_name}/dvc"
    subprocess.call(
        ["dvc", "remote", "add", "-d", "-f", REMOTE_NAME, remote_url]
    )
    subprocess.call(["dvc", "remote", "modify", REMOTE_NAME, "auth", "custom"])


def set_remote_auth():
    """Get a token and set it in the local config so we can interact with
    the API.
    """
    token = calkit.auth()
    subprocess.call(
        [
            "dvc",
            "remote",
            "modify",
            "--local",
            REMOTE_NAME,
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
            REMOTE_NAME,
            "password",
            f"Bearer {token}",
        ]
    )
