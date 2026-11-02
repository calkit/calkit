"""Test configuration shared across the suite."""

import functools
import os
import shutil
import subprocess

import pytest


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
            return "Docker is not usable: " + res.stderr.decode().strip()
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
    raise ValueError(f"Unknown tool '{tool}'")


def pytest_runtest_setup(item: pytest.Item) -> None:
    # CI has everything, so a missing tool there is a failure, not a skip
    if os.getenv("CI"):
        return
    for marker in item.iter_markers("needs"):
        for tool in marker.args:
            reason = get_missing_reason(tool)
            if reason is not None:
                pytest.skip(reason)
