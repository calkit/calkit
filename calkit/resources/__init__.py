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
ACTIONS_PATH = "calkit/calkit/actions"
ACTION_PATH = f"{ACTIONS_PATH}/run"
# The ref the example workflow ships with, which gets pinned to a released
# version of Calkit when there is one to pin to
ACTION_REF = f"{ACTION_PATH}@main"
# The run action used to live in its own repo, and workflows written before
# it moved still point there
LEGACY_ACTION_PATHS = ["calkit/run-action"]
# Calkit's actions as of this version, which share its release tags, so a
# workflow's refs to them can be pinned to it
ACTION_NAMES = ["run"]
ACTION_USES_PATTERN = re.compile(
    r"(?m)^(?P<prefix>\s*(?:-\s+)?uses:\s*)(?P<quote>['\"]?)"
    + r"(?P<path>"
    + "|".join(
        [re.escape(ACTIONS_PATH) + r"/(?P<name>[\w-]+)"]
        + [re.escape(p) for p in LEGACY_ACTION_PATHS]
    )
    + r")@(?P<ref>[^\s'\"#]+)(?P=quote)"
)
# The workflow Calkit writes to run the pipeline, and the other spelling
# that's taken as it
RUN_WORKFLOW_FNAME = "run-calkit.yml"
RUN_WORKFLOW_FNAMES = [RUN_WORKFLOW_FNAME, "run-calkit.yaml"]


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


def get_latex_workshop_settings(
    settings: dict, projects: list[tuple[str, dict]]
) -> dict:
    """Return VS Code settings with LaTeX Workshop building a project's
    documents the way its pipeline does.

    ``projects`` are ``(path, ck_info)`` for the project and each of its
    subprojects, as ``calkit.core.iter_projects`` yields them. The bundled
    settings build in Calkit's LaTeX Docker image, which a project keeps
    unless a LaTeX stage in it or a subproject uses a TeX Live environment,
    or a switch that can pick one, or it has no LaTeX stages and only one
    TeX Live environment. Then one recipe builds every document with
    ``calkit latex build --as-stage``, which finds the stage for the
    document LaTeX Workshop builds, so each builds in its stage's
    environment, Docker or not, with its options. A recipe per stage would
    have LaTeX Workshop pick one on save by its position or last use, not
    by the document. Builds are verbose, with errors named by file and
    line, since that's how LaTeX Workshop finds them in TeX's output.
    """
    from calkit.environments import SWITCH_KIND
    from calkit.models.pipeline import LatexStage

    def uses_texlive(env: Any, envs: dict) -> bool:
        if not isinstance(env, dict):
            return False
        if env.get("kind") == "texlive":
            return True
        if env.get("kind") != SWITCH_KIND:
            return False
        # A switch's options may be named or defined in place
        for option in env.get("switch") or []:
            use = option.get("use") if isinstance(option, dict) else None
            if isinstance(use, str):
                use = envs.get(use)
            if isinstance(use, dict) and use.get("kind") == "texlive":
                return True
        return False

    uses_stages = False
    n_texlive_envs = 0
    # Where each stage puts its PDF, relative to the root, if not beside
    # the document
    out_dirs: set[str | None] = set()
    for path, ck_info in projects:
        envs = ck_info.get("environments") or {}
        stages = (ck_info.get("pipeline") or {}).get("stages") or {}
        n_texlive_envs += sum(
            isinstance(env, dict) and env.get("kind") == "texlive"
            for env in envs.values()
        )
        for name, stage in stages.items():
            if not isinstance(stage, dict) or stage.get("kind") != "latex":
                continue
            try:
                s = LatexStage.model_validate(stage | {"name": name})
            except ValueError:
                continue
            if s.environment is not None and uses_texlive(
                envs.get(s.environment), envs
            ):
                uses_stages = True
            if s.latexmkrc_path is None and s.output_dir is not None:
                pdf_path = posixpath.join(path, s.wdir or "", s.pdf_path)
                out_dirs.add(posixpath.dirname(posixpath.normpath(pdf_path)))
            else:
                out_dirs.add(None)
    if not (uses_stages or (not out_dirs and n_texlive_envs == 1)):
        return settings
    settings = dict(settings)
    settings.pop("latex-workshop.docker.image.latex", None)
    settings["latex-workshop.docker.enabled"] = False
    # A magic comment, e.g., % !TEX program = xelatex, would bypass the
    # recipe and run the machine's TeX
    settings["latex-workshop.latex.build.enableMagicComments"] = False
    settings["latex-workshop.latex.tools"] = [
        {
            "name": "Calkit",
            "command": "calkit",
            "args": [
                "latex",
                "build",
                "--as-stage",
                "--verbose",
                "--latexmk-arg",
                "-file-line-error",
                "%DOC_EXT%",
            ],
            "cwd": "%WORKSPACE_FOLDER%",
        }
    ]
    settings["latex-workshop.latex.recipes"] = [
        {"name": "Calkit", "tools": ["Calkit"]}
    ]
    # Over a default a user may have set by name
    settings["latex-workshop.latex.recipe.default"] = "first"
    # LaTeX Workshop finds every document's PDF, and its SyncTeX, in one
    # place, so it's where the stages' output_dir puts them if they all
    # agree, and otherwise beside each document
    out_dir = out_dirs.pop() if len(out_dirs) == 1 else None
    if out_dir is not None:
        out_dir = posixpath.normpath(out_dir)
        settings["latex-workshop.latex.outDir"] = "%WORKSPACE_FOLDER%" + (
            f"/{out_dir}" if out_dir != "." else ""
        )
    return settings


def make_vscode_settings(
    ck_info: dict | None = None, wdir: str | None = None
) -> str:
    """Return the VS Code settings for a project, as JSON text."""
    from calkit.core import iter_projects

    settings = load_json("vscode", "settings.json")
    projects = list(iter_projects(wdir=wdir, ck_info=ck_info))
    return (
        json.dumps(get_latex_workshop_settings(settings, projects), indent=2)
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
        vscode["settings"], projects
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
    of Calkit that wrote its workflow, or for a development build, the
    release it's based on.
    """
    if version is None:
        import calkit

        version = calkit.__version__
    match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?P<dev>\.dev\d+(?:\+.+)?)?", version
    )
    if match is None:
        return ACTION_REF
    major, minor, patch = (int(n) for n in match.groups()[:3])
    # Development builds, e.g., 0.51.1.dev19+gc4093debd, aren't tags, but
    # hatch-vcs numbers them by bumping the patch of the release they're
    # based on, which is fixed, unlike main
    if match["dev"]:
        if patch == 0:
            return ACTION_REF
        patch -= 1
    return f"{ACTION_PATH}@v{major}.{minor}.{patch}"


def get_action_name(match: re.Match[str]) -> str | None:
    """Return which of Calkit's actions a ``uses`` line matched by
    ``ACTION_USES_PATTERN`` refers to, or None if it isn't one of this
    version's.
    """
    if match.group("path") in LEGACY_ACTION_PATHS:
        return "run"
    name = match.group("name")
    return name if name in ACTION_NAMES else None


def uses_run_action(workflow_txt: str) -> bool:
    """Return whether a workflow runs the Calkit action, at any ref."""
    return any(
        get_action_name(m) == "run"
        for m in ACTION_USES_PATTERN.finditer(workflow_txt)
    )


def set_action_ref(workflow_txt: str, version: str | None = None) -> str:
    """Point a workflow's Calkit action refs at a version of Calkit.

    Only the ``uses`` lines are touched, so a project that has customized
    its workflow keeps those customizations. Refs to the run action's
    previous home get migrated in the process. Refs pinned to a commit are
    left as they are, since that was chosen over a release.
    """

    def replace(m: re.Match[str]) -> str:
        name = get_action_name(m)
        if name is None or re.fullmatch(r"[0-9a-f]{40}", m.group("ref")):
            return m.group(0)
        quote = m.group("quote")
        return f"{m.group('prefix')}{quote}{ACTIONS_PATH}/{name}@{ref}{quote}"

    _, _, ref = get_action_ref(version).partition("@")
    return ACTION_USES_PATTERN.sub(replace, workflow_txt)


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


def find_workflows(wdir: str | None = None) -> list[tuple[str, str]]:
    """Return the names and text of a project's workflows that use any of
    Calkit's actions.

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
        if any(get_action_name(m) for m in ACTION_USES_PATTERN.finditer(txt)):
            found.append((fname, txt))
    return found


def find_run_workflows(wdir: str | None = None) -> list[tuple[str, str]]:
    """Return the names and text of a project's workflows that run the
    Calkit action.
    """
    return [
        (f, txt) for f, txt in find_workflows(wdir) if uses_run_action(txt)
    ]


def get_pipeline_workflow_fname(fnames: list[str]) -> str | None:
    """Return which of a project's workflows that run the Calkit action is
    the one that runs its pipeline, or None if that's ambiguous.

    That's the one Calkit writes, else the only one, since another might,
    e.g., run the action to build and deploy a website.
    """
    for fname in RUN_WORKFLOW_FNAMES:
        if fname in fnames:
            return fname
    if len(fnames) == 1:
        return fnames[0]
    return None


def get_ambiguous_workflows_message(fnames: list[str]) -> str:
    """Return the message for when it's unclear which of several workflows
    that run the Calkit action runs the pipeline.
    """
    return (
        f"Several workflows run the Calkit action ({', '.join(fnames)}), "
        "so it's unclear which runs the pipeline; "
        f"rename that one to {RUN_WORKFLOW_FNAME}"
    )


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
        txt = set_action_ref(txt, version="main")
        return txt.replace("\r\n", "\n").strip()

    return normalize(workflow_txt) == normalize(
        read_text("github-actions", GITHUB_ACTIONS_FNAME)
    )
