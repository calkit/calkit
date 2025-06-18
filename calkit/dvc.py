"""Working with DVC."""

from __future__ import annotations

import logging
import os
import subprocess
import sys

import dvc.repo
import git

import calkit
from calkit.cli import warn
from calkit.config import get_app_name

logger = logging.getLogger(__package__)
logger.setLevel(logging.INFO)


def configure_remote(wdir: str = None):
    try:
        project_name = calkit.detect_project_name(wdir=wdir)
    except ValueError as e:
        raise ValueError(f"Can't detect project name: {e}")
    # If Git origin is not set, set that
    repo = git.Repo(wdir)
    try:
        repo.remote()
    except ValueError:
        warn("No Git remote defined; querying Calkit Cloud")
        # Try to fetch Git repo URL from Calkit cloud
        try:
            project = calkit.cloud.get(f"/projects/{project_name}")
            url = project["git_repo_url"]
        except Exception as e:
            raise ValueError(f"Could not fetch project info: {e}")
        if not url.endswith(".git"):
            url += ".git"
        repo.git.remote(["add", "origin", url])
    base_url = calkit.cloud.get_base_url()
    remote_url = f"{base_url}/projects/{project_name}/dvc"
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "dvc",
            "remote",
            "add",
            "-d",
            "-f",
            get_app_name(),
            remote_url,
        ],
        cwd=wdir,
    )
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "dvc",
            "remote",
            "modify",
            get_app_name(),
            "auth",
            "custom",
        ],
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
            sys.executable,
            "-m",
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
            sys.executable,
            "-m",
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


def add_external_remote(owner_name: str, project_name: str) -> dict:
    base_url = calkit.cloud.get_base_url()
    remote_url = f"{base_url}/projects/{owner_name}/{project_name}/dvc"
    remote_name = f"{get_app_name()}:{owner_name}/{project_name}"
    subprocess.call(
        [
            sys.executable,
            "-m",
            "dvc",
            "remote",
            "add",
            "-f",
            remote_name,
            remote_url,
        ]
    )
    subprocess.call(
        [
            sys.executable,
            "-m",
            "dvc",
            "remote",
            "modify",
            remote_name,
            "auth",
            "custom",
        ]
    )
    set_remote_auth(remote_name)
    return {"name": remote_name, "url": remote_url}


def read_pipeline(wdir: str = ".") -> dict:
    fpath = os.path.join(wdir, "dvc.yaml")
    if not os.path.isfile(fpath):
        return {}
    with open(fpath) as f:
        return calkit.ryaml.load(f)


def get_remotes(wdir: str | None = None) -> dict[str, str]:
    """Get a dictionary of DVC remotes, keyed by name, with URL as the
    value.
    """
    out = (
        subprocess.check_output(
            [sys.executable, "-m", "dvc", "remote", "list"], cwd=wdir
        )
        .decode()
        .strip()
    )
    if not out:
        return {}
    resp = {}
    out = out.replace("(default)", "").strip()
    is_name = True
    for token in out.split():
        token = token.strip()
        if is_name:
            name = token
        else:
            url = token
            resp[name] = url
        is_name = not is_name
    return resp


def list_paths(wdir: str = None, recursive=False) -> list[str]:
    """List paths tracked with DVC."""
    return [p.get("path") for p in list_files(wdir=wdir, recursive=recursive)]


def list_files(wdir: str = None, recursive=True) -> list[dict]:
    """Return a list with all files in DVC, including their path and md5
    checksum.
    """
    dvc_repo = dvc.repo.Repo(wdir)
    return dvc_repo.ls(".", dvc_only=True, recursive=recursive)


def get_output_revisions(path: str):
    """Get all revisions of a pipeline output."""
    pass
