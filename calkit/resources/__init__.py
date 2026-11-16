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
import posixpath
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


def get_latex_workshop_settings(settings: dict, ck_info: dict) -> dict:
    """Return VS Code settings with LaTeX Workshop building a project's
    documents the way its pipeline does.

    The bundled settings build in Calkit's LaTeX Docker image, which a
    project keeps unless its LaTeX stages use a TeX Live environment. Then
    each of those stages gets a recipe that runs ``calkit latex build`` in
    its environment with its options, with stages that build alike sharing
    one. A project without LaTeX stages gets one for its only TeX Live
    environment, if it has one. Builds are verbose, with errors named by
    file and line, since that's how LaTeX Workshop finds them in TeX's
    output.
    """
    from calkit.models.pipeline import LatexStage

    envs = ck_info.get("environments") or {}
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    texlive_names = [
        name
        for name, env in envs.items()
        if isinstance(env, dict) and env.get("kind") == "texlive"
    ]
    latex_stages = []
    for name, stage in stages.items():
        if not isinstance(stage, dict) or stage.get("kind") != "latex":
            continue
        try:
            latex_stages.append(
                LatexStage.model_validate(stage | {"name": name})
            )
        except ValueError:
            continue
    # Each build's working directory and arguments, with the stages it's for
    builds: dict[tuple[str, ...], list[str]] = {}
    # Where each puts its PDF, if not beside the document
    out_dirs: set[str | None] = set()
    for s in latex_stages:
        if s.environment not in texlive_names:
            continue
        key = (s.wdir or "", "-e", s.environment, *s.build_args)
        builds.setdefault(key, []).append(str(s.name))
        if s.latexmkrc_path is None and s.output_dir is not None:
            pdf_path = posixpath.join(s.wdir or "", s.pdf_path)
            out_dirs.add(posixpath.dirname(posixpath.normpath(pdf_path)))
        else:
            out_dirs.add(None)
    if not latex_stages and len(texlive_names) == 1:
        builds[("", "-e", texlive_names[0])] = [texlive_names[0]]
    if not builds:
        return settings
    settings = dict(settings)
    settings.pop("latex-workshop.docker.image.latex", None)
    settings["latex-workshop.docker.enabled"] = False
    tools = []
    for (wdir, *args), names in builds.items():
        if "--verbose" not in args:
            args.append("--verbose")
        args += ["--latexmk-arg", "-file-line-error"]
        tools.append(
            {
                "name": "Calkit: " + ", ".join(names),
                "command": "calkit",
                "args": ["latex", "build", *args, "%DOC_EXT%"],
                "cwd": posixpath.join("%WORKSPACE_FOLDER%", wdir).rstrip("/"),
            }
        )
    settings["latex-workshop.latex.tools"] = tools
    settings["latex-workshop.latex.recipes"] = [
        {"name": tool["name"], "tools": [tool["name"]]} for tool in tools
    ]
    # LaTeX Workshop finds the PDF, and its SyncTeX, where the stage's
    # output_dir puts it, if they all put it in one place
    out_dir = out_dirs.pop() if len(out_dirs) == 1 else None
    if out_dir is not None:
        settings["latex-workshop.latex.outDir"] = "%WORKSPACE_FOLDER%" + (
            f"/{out_dir}" if out_dir else ""
        )
    return settings


def make_vscode_settings(
    ck_info: dict | None = None, wdir: str | None = None
) -> str:
    """Return the VS Code settings for a project, as JSON text."""
    if ck_info is None:
        from calkit.core import load_calkit_info

        ck_info = load_calkit_info(wdir=wdir, read_only=True)
    settings = load_json("vscode", "settings.json")
    return (
        json.dumps(get_latex_workshop_settings(settings, ck_info), indent=2)
        + "\n"
    )


def make_devcontainer_spec(
    ck_info: dict | None = None, wdir: str | None = None
) -> str:
    """Return the dev container spec for a project, as JSON text.

    Julia is only installed for a project with a Julia environment, in it
    or a subproject, since installing it slows down creating every
    Codespace. LaTeX Workshop builds as ``make_vscode_settings`` sets it to.
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
    projects = list(iter_projects(wdir=wdir, ck_info=ck_info))
    vscode = spec["customizations"]["vscode"]
    vscode["settings"] = get_latex_workshop_settings(
        vscode["settings"], projects[0][1]
    )
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
