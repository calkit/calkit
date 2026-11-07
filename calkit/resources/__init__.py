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

import io
import json
import os
import re
import stat
from typing import Any

DEVCONTAINER_FNAME = "devcontainer.json"
VSCODE_FNAMES = ["settings.json", "extensions.json"]
GITHUB_ACTIONS_FNAME = "example.yml"
# Bigger than any workflow, so a file this size isn't read as one
MAX_WORKFLOW_BYTES = 1_000_000
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
    shared recommendations minus any the base excludes, so a project gets
    nearly the same setup whether or not it's opened in a container.
    """
    spec = load_json("devcontainer", "base.json")
    base = spec.setdefault("customizations", {}).get("vscode", {})
    settings = load_json("vscode", "settings.json")
    # Container-only settings win, since they exist to override how things
    # work inside the container
    settings |= base.get("settings", {})
    # The base leaves out extensions with a "-" prefix, which the dev
    # container spec also reads as "don't install", e.g., one Codespaces adds
    excluded = [e for e in base.get("extensions", []) if e.startswith("-")]
    skipped = {e[1:].lower() for e in excluded}
    recommended = load_json("vscode", "extensions.json")["recommendations"]
    vscode = {
        "extensions": [e for e in recommended if e.lower() not in skipped]
        + excluded,
        "settings": settings,
    }
    # Anything else the base customizes, e.g., a future `snippets` key, is
    # kept as-is
    for key, value in base.items():
        vscode.setdefault(key, value)
    spec["customizations"]["vscode"] = vscode
    return spec


def make_devcontainer_spec(
    ck_info: dict | None = None, wdir: str | None = None
) -> str:
    """Return the dev container spec for a project, as JSON text.

    Julia is only installed for a project with a Julia environment, in it
    or a subproject, since installing it slows down creating every
    Codespace.
    """
    from calkit.core import iter_projects

    def uses_julia(env: Any) -> bool:
        if not isinstance(env, dict):
            return False
        # A switch's options may be defined in place
        options = [
            o.get("use")
            for o in env.get("switch") or []
            if isinstance(o, dict)
        ]
        return env.get("kind") == "julia" or any(map(uses_julia, options))

    spec = load_json("devcontainer", DEVCONTAINER_FNAME)
    projects = iter_projects(wdir=wdir, ck_info=ck_info)
    if not any(
        uses_julia(env)
        for _, info in projects
        for env in (info.get("environments") or {}).values()
    ):
        features = spec.get("features", {})
        for key in list(features):
            if key.startswith(
                "ghcr.io/julialang/devcontainer-features/julia:"
            ):
                del features[key]
        vscode = spec["customizations"]["vscode"]
        vscode["extensions"] = [
            e
            for e in vscode["extensions"]
            if e.lower() != "julialang.language-julia"
        ]
    return json.dumps(spec, indent=2) + "\n"


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


def set_workflow_triggers(
    workflow_txt: str, on: str | list[str] | dict[str, Any]
) -> str:
    """Return a workflow with its ``on`` triggers replaced, keeping the rest
    as it was.

    Event names become a mapping with no settings for each, e.g.,
    ``workflow_dispatch:``, which is how GitHub's docs write them. A mapping
    is used as is, e.g., ``{"push": {"branches": ["main"]}}``.
    """
    from ruamel.yaml.comments import CommentedMap

    from calkit.core import ryaml

    workflow = ryaml.load(workflow_txt)
    if isinstance(on, str):
        on = [on]
    triggers = (
        CommentedMap(on)
        if isinstance(on, dict)
        else CommentedMap((name, None) for name in on)
    )
    # YAML 1.1 parsers read the key as true, so it might be quoted either way
    key: Any = True if True in workflow and "on" not in workflow else "on"
    workflow[key] = triggers
    buf = io.StringIO()
    ryaml.dump(workflow, buf)
    return buf.getvalue()


def render_github_actions_workflow(
    version: str | None = None,
    on: str | list[str] | dict[str, Any] | None = None,
) -> str:
    """Return the example workflow, pinning the action to a Calkit version.

    ``on`` replaces its triggers, e.g., ``["workflow_dispatch"]`` for one
    that only runs when started, e.g., from the hub, rather than on every
    push, which for a paper synced from Overleaf is every sync.
    """
    txt = set_action_ref(
        read_text("github-actions", GITHUB_ACTIONS_FNAME), version=version
    )
    if on is not None:
        txt = set_workflow_triggers(txt, on)
    return txt


def find_run_workflows(wdir: str | None = None) -> list[tuple[str, str]]:
    """Return the names and text of a project's workflows that run the
    Calkit action.

    Symlinks, anything that isn't a regular file, and files too big to be
    a workflow are skipped, since the hub reads these from repos anyone can
    push to.
    """
    root = os.path.realpath(wdir or ".")
    workflows_dir = os.path.join(root, ".github", "workflows")
    if not os.path.realpath(workflows_dir).startswith(root + os.sep):
        return []
    if not os.path.isdir(workflows_dir):
        return []
    found = []
    for fname in sorted(os.listdir(workflows_dir)):
        fpath = os.path.join(workflows_dir, fname)
        if not (fname.endswith(".yaml") or fname.endswith(".yml")):
            continue
        st = os.lstat(fpath)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_WORKFLOW_BYTES:
            continue
        with open(fpath, encoding="utf-8", errors="replace") as f:
            txt = f.read()
        if uses_run_action(txt):
            found.append((fname, txt))
    return found


def can_start_workflow(workflow_txt: str) -> bool:
    """Return whether a workflow can be started on demand, i.e., it has a
    ``workflow_dispatch`` trigger.
    """
    from calkit.core import ryaml

    try:
        workflow = ryaml.load(workflow_txt)
    except Exception:
        return False
    if not isinstance(workflow, dict):
        return False
    # YAML 1.1 parsers read the key as true, so a workflow written by one
    # might have it quoted either way
    triggers = workflow.get("on", workflow.get(True))
    if isinstance(triggers, str):
        triggers = [triggers]
    return "workflow_dispatch" in (triggers or [])


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
