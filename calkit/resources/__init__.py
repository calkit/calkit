"""Bundled project resources.

These are the dev container and VS Code configs that get copied into projects
by ``calkit update devcontainer`` and ``calkit update vscode-config``. They
ship with the package, so installing them into a project never requires a
download, and they always match the installed version of Calkit.

The dev container spec's VS Code customizations are generated from the shared
VS Code config, which keeps the two in sync. Run ``make sync-resources`` after
editing ``vscode/*.json`` or ``devcontainer/base.json``.
"""

from __future__ import annotations

import json
import os
import re

DEVCONTAINER_FNAME = "devcontainer.json"
VSCODE_FNAMES = ["settings.json", "extensions.json"]
GITHUB_ACTIONS_FNAME = "example.yml"
# The ref the example workflow ships with, which gets pinned to a released
# version of Calkit when there is one to pin to
ACTION_REF = "calkit/calkit/actions/run@main"


def get_dir() -> str:
    """Return the directory containing the bundled resources."""
    return os.path.dirname(os.path.abspath(__file__))


def read_text(*relpath: str) -> str:
    """Read a bundled resource file as text."""
    with open(os.path.join(get_dir(), *relpath), encoding="utf-8") as f:
        return f.read()


def load_json(*relpath: str) -> dict:
    """Load a bundled JSON resource file."""
    data: dict = json.loads(read_text(*relpath))
    return data


def render_devcontainer_spec() -> dict:
    """Build the dev container spec from its base and the VS Code config.

    The spec's ``settings`` are the shared VS Code settings plus the
    container-only ones defined in the base, and its ``extensions`` are the
    shared recommendations, so a project gets the same setup whether or not
    it's opened in a container.
    """
    spec = load_json("devcontainer", "base.json")
    settings = load_json("vscode", "settings.json")
    # Container-only settings win, since they exist to override how things
    # work inside the container
    settings |= (
        spec.get("customizations", {}).get("vscode", {}).get("settings", {})
    )
    extensions = load_json("vscode", "extensions.json")["recommendations"]
    spec.setdefault("customizations", {})["vscode"] = {
        "extensions": extensions,
        "settings": settings,
    }
    return spec


def render_github_actions_workflow(version: str | None = None) -> str:
    """Return the example workflow, pinning the action to a Calkit version.

    The action lives in this repo at ``actions/run``, so its refs are
    Calkit's own release tags, and a project ends up pinned to the version
    of Calkit that wrote its workflow. Rerunning ``calkit update github-actions`` after
    upgrading moves the pin.
    """
    txt = read_text("github-actions", GITHUB_ACTIONS_FNAME)
    if version is None:
        import calkit

        version = calkit.__version__
    # Development installs report versions like 0.42.2.dev0+g21c9bb93, which
    # isn't a tag anyone can reference, so those stay on main
    if re.fullmatch(r"\d+\.\d+\.\d+", version):
        txt = txt.replace(ACTION_REF, f"calkit/calkit/actions/run@v{version}")
    return txt
