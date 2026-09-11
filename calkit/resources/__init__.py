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
ACTION_PATH = "calkit/calkit/actions/run"
# The ref the example workflow ships with, which gets pinned to a released
# version of Calkit when there is one to pin to
ACTION_REF = f"{ACTION_PATH}@main"
# The action used to live in its own repo, and workflows written before it
# moved still point there
LEGACY_ACTION_PATHS = ["calkit/run-action"]
ACTION_USES_PATTERN = re.compile(
    r"(?m)^(?P<prefix>\s*(?:-\s+)?uses:\s*)(?P<quote>['\"]?)"
    + r"(?:"
    + "|".join(re.escape(p) for p in [ACTION_PATH] + LEGACY_ACTION_PATHS)
    + r")@[^\s'\"#]+(?P=quote)"
)


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
    base = spec.setdefault("customizations", {}).get("vscode", {})
    settings = load_json("vscode", "settings.json")
    # Container-only settings win, since they exist to override how things
    # work inside the container
    settings |= base.get("settings", {})
    vscode = {
        "extensions": load_json("vscode", "extensions.json")[
            "recommendations"
        ],
        "settings": settings,
    }
    # Anything else the base customizes, e.g., a future `snippets` key, is
    # kept as-is
    for key, value in base.items():
        vscode.setdefault(key, value)
    spec["customizations"]["vscode"] = vscode
    return spec


def get_action_ref(version: str | None = None) -> str:
    """Return the run action ref matching a version of Calkit.

    The action lives in this repo at ``actions/run``, so its refs are
    Calkit's own release tags, and a project ends up pinned to the version
    of Calkit that wrote its workflow.
    """
    if version is None:
        import calkit

        version = calkit.__version__
    # Development installs report versions like 0.42.2.dev0+g21c9bb93, which
    # isn't a tag anyone can reference, so those stay on main
    if re.fullmatch(r"\d+\.\d+\.\d+", version):
        return f"{ACTION_PATH}@v{version}"
    return ACTION_REF


def uses_run_action(workflow_txt: str) -> bool:
    """Return whether a workflow runs the Calkit action, at any ref."""
    return ACTION_USES_PATTERN.search(workflow_txt) is not None


def set_action_ref(workflow_txt: str, version: str | None = None) -> str:
    """Point a workflow's Calkit action refs at a version of Calkit.

    Only the ``uses`` lines are touched, so a project that has customized
    its workflow keeps those customizations. Refs to the action's previous
    home get migrated in the process.
    """
    ref = get_action_ref(version)
    return ACTION_USES_PATTERN.sub(
        lambda m: (
            m.group("prefix") + m.group("quote") + ref + m.group("quote")
        ),
        workflow_txt,
    )


def render_github_actions_workflow(version: str | None = None) -> str:
    """Return the example workflow, pinning the action to a Calkit version."""
    return set_action_ref(
        read_text("github-actions", GITHUB_ACTIONS_FNAME), version=version
    )


def is_default_github_actions_workflow(workflow_txt: str) -> bool:
    """Return whether a workflow is the example, unmodified.

    Its action ref is ignored, since that gets pinned to whichever version
    of Calkit wrote the workflow, as are line endings, which Git may have
    translated on checkout.
    """

    def normalize(txt: str) -> str:
        txt = ACTION_USES_PATTERN.sub(
            lambda m: m.group("prefix") + ACTION_REF, txt
        )
        return txt.replace("\r\n", "\n").strip()

    return normalize(workflow_txt) == normalize(
        read_text("github-actions", GITHUB_ACTIONS_FNAME)
    )
