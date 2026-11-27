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
    ``CALKIT_TEST_TEXLIVE_HOME`` names one to keep between runs, as CI
    does, so the archive is asked only for packages it doesn't have yet.

    Skips if TeX Live's historic archive can't be reached and nothing's
    been downloaded from it yet.
    """
    import requests

    from calkit.environments import texlive

    home = os.environ.get("CALKIT_TEST_TEXLIVE_HOME")
    if home:
        os.makedirs(home, exist_ok=True)
    else:
        home = str(tmp_path_factory.mktemp("texlive-home"))
    # Downloaded from before, so it needn't be reachable now
    tlpdb_dir = os.path.join(home, ".calkit", "texlive", "tlpdb")
    if os.path.isdir(tlpdb_dir) and os.listdir(tlpdb_dir):
        return home
    url = texlive.FROZEN_REPOSITORY_TEMPLATE.format(
        release=texlive.DEFAULT_RELEASE
    )
    try:
        requests.head(
            url + "/tlpkg/texlive.tlpdb.xz", timeout=30
        ).raise_for_status()
    except requests.RequestException as e:
        pytest.skip(f"TeX Live's archive can't be reached: {e}")
    return home


KIT_PROJECT_SCRIPT = """\
import os

import pypdfium2 as pdfium
from PIL import Image

os.makedirs("figures", exist_ok=True)
rows = open("data/raw.csv").read().splitlines()[1:]
Image.new("RGB", (64, len(rows) % 64 + 1), "red").save("figures/fig.png")
pdf = pdfium.PdfDocument.new()
pdf.new_page(200, 100)
pdf.save("figures/fig.pdf")
pdf.close()
with open("figures/fig.svg", "w") as f:
    f.write('<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>\\n')
with open("figures/page.html", "w") as f:
    f.write("<!DOCTYPE html><html><body><p>Hi</p></body></html>\\n")
"""


@pytest.fixture
def kit_project(tmp_dir) -> None:
    """A committed project whose one stage makes a PNG, PDF, SVG, and HTML
    page from a DVC-tracked CSV, for testing kits.
    """
    import sys

    import calkit

    os.makedirs("scripts")
    os.makedirs("data")
    with open("scripts/make.py", "w") as f:
        f.write(KIT_PROJECT_SCRIPT)
    with open("data/raw.csv", "w") as f:
        f.write("x,y\n" + "".join(f"{i},{i * i}\n" for i in range(5000)))
    outputs = [
        "figures/fig.png",
        "figures/fig.pdf",
        "figures/fig.svg",
        "figures/page.html",
    ]
    ck_info = {
        "name": "kit-test",
        "title": "Kit test",
        "pipeline": {
            "stages": {
                "make": {
                    "kind": "command",
                    "environment": "_system",
                    "command": f"{sys.executable} scripts/make.py",
                    "inputs": ["scripts/make.py", "data/raw.csv"],
                    "outputs": outputs,
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    for cmd in [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@test.com"],
        ["git", "config", "user.name", "Test"],
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://user:token@github.com/someone/kit-test.git",
        ],
        ["dvc", "init", "-q"],
        ["dvc", "config", "core.analytics", "false"],
        ["git", "add", "calkit.yaml", "scripts", ".dvc", ".dvcignore"],
        ["git", "commit", "-qm", "init"],
        [sys.executable, "-m", "calkit", "add", "--to", "dvc", "data/raw.csv"],
        ["git", "commit", "-qm", "Add data"],
        [sys.executable, "-m", "calkit", "run"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "Run"],
    ]:
        subprocess.check_call(cmd)
