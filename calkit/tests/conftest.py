"""Test configuration shared across the suite."""

import functools
import os
import shutil
import subprocess

import pytest

TOOLS = ["docker", "juliaup", "chrome"]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "needs(*tools): skip unless each tool, e.g., 'docker', is usable, "
        "except in CI, which installs them all",
    )


@functools.cache
def get_missing_reason(tool: str) -> str | None:
    """Why a tool can't be used here, or None if it can."""
    if tool == "docker":
        if shutil.which("docker") is None:
            return "Docker is not installed"
        # Installed isn't enough: the daemon must be running and ours to use
        try:
            res = subprocess.run(
                ["docker", "info"], capture_output=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            return "Docker did not answer"
        if res.returncode != 0:
            stderr = res.stderr.decode(errors="replace").strip()
            return "Docker is not usable: " + stderr
        return None
    if tool == "juliaup":
        if shutil.which("juliaup") is None:
            return "Juliaup is not installed"
        return None
    if tool == "chrome":
        # Where Kaleido looks for it
        names = [
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "chrome",
        ]
        if any(shutil.which(name) for name in names) or os.path.isdir(
            "/Applications/Google Chrome.app"
        ):
            return None
        return "Chrome is not installed"
    return None


def pytest_runtest_setup(item: pytest.Item) -> None:
    tools = [t for m in item.iter_markers("needs") for t in m.args]
    # Checked even in CI, where a misspelled tool would never be looked up
    unknown = sorted(set(tools) - set(TOOLS))
    if unknown:
        raise ValueError(f"Unknown tools for 'needs': {unknown}")
    # CI has everything, so a missing tool there is a failure, not a skip
    if os.getenv("CI", "").lower() not in ("", "0", "false"):
        return
    for tool in tools:
        reason = get_missing_reason(tool)
        if reason is not None:
            pytest.skip(reason)


@pytest.fixture(scope="session")
def texlive_user_home(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A Calkit home whose TeX Live store is shared by the tests that build
    TeX Live environments, so packages download and formats build once per
    worker. Mark such tests with ``xdist_group("texlive")`` to share it.

    Skips if TeX Live's historic archive can't be reached.
    """
    import requests

    from calkit.environments import texlive

    url = texlive.FROZEN_REPOSITORY_TEMPLATE.format(
        release=texlive.DEFAULT_RELEASE
    )
    try:
        requests.head(
            url + "/tlpkg/texlive.tlpdb.xz", timeout=30
        ).raise_for_status()
    except requests.RequestException as e:
        pytest.skip(f"TeX Live's archive can't be reached: {e}")
    return str(tmp_path_factory.mktemp("texlive-home"))
