"""Figure scripts: a script written in the browser becomes a pipeline stage.

The figure editor runs Python in the browser so a figure can be iterated on with
nothing installed, but a browser run is not a reproducible one. Saving is
what makes it real: the script is committed, a stage is declared that reads
the data and writes the figure, and an environment exists for the stage to
run in. From then on the figure traces back to code, data, and environment
like any other pipeline output.
"""

import logging
import os
import posixpath
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import app.projects
import calkit.pipeline
from app import mixpanel
from app.api.deps import CurrentUser, SessionDep
from app.api.routes.projects.core import _validate_ck_stage
from app.core import ryaml
from app.formatting import format_python
from app.git import get_ck_info_from_repo, get_repo, record_project_update
from app.models import Figure

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter()

# Environment kinds a Python script can run in, in order of preference when
# the project has more than one.
PYTHON_ENV_KINDS = ("uv", "uv-venv", "pixi", "conda", "venv")
# Raster and vector images, plus what interactive plotting libraries write:
# plotly's figure JSON and standalone HTML
FIGURE_SUFFIXES = (
    ".png",
    ".svg",
    ".pdf",
    ".jpg",
    ".jpeg",
    ".webp",
    ".json",
    ".html",
)


class FigureScriptPost(BaseModel):
    figure_path: str
    title: str
    description: str | None = None
    script_path: str
    script_content: str
    # Files the script reads, declared as the stage's inputs so a change to
    # the data reruns the stage.
    inputs: list[str] = Field(default_factory=list)
    # PyPI names the script imports, for the environment spec.
    packages: list[str] = Field(default_factory=list)
    # An existing environment to run in; None picks the project's Python
    # environment, or creates one when there isn't any.
    environment: str | None = None
    # The stage this figure already comes from, when editing rather than
    # creating. Its script is overwritten and its inputs replaced; the stage
    # keeps its name and anything else declared on it.
    stage: str | None = None
    message: str | None = None


class FigureScriptResult(BaseModel):
    figure: Figure
    stage_name: str
    environment: str
    environment_created: bool
    # Packages the script imports that the environment spec doesn't list
    # and that couldn't be added automatically.
    packages_missing: list[str]
    # The script as committed, which is the submitted one formatted
    script_content: str


def _clean_rel_path(path: str, what: str) -> str:
    """Normalize a repo-relative POSIX path, refusing anything that escapes.

    The paths are written straight into the repo and calkit.yaml, so a
    leading slash or a `..` segment is an error rather than something to
    quietly resolve.
    """
    cleaned = posixpath.normpath(path.strip().replace("\\", "/"))
    if (
        not cleaned
        or cleaned in (".", "..")
        or cleaned.startswith("/")
        or cleaned.startswith("../")
        or re.match(r"^[A-Za-z]:", cleaned)
    ):
        raise HTTPException(422, f"Invalid {what} path: {path!r}")
    return cleaned


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "figure"


def _spec_lists_package(spec_text: str, package: str) -> bool:
    # Requirements files list bare names; pyproject and pixi quote them or
    # key them; conda YAML prefixes with "- ". One pattern covers all: the
    # name at the start of a line, optionally after a dash, quote, or space,
    # and followed by something that isn't part of a longer name.
    pattern = rf"(?im)^\s*[-\"']?\s*{re.escape(package)}(?![A-Za-z0-9_.-])"
    return re.search(pattern, spec_text) is not None


def _add_packages_to_spec(
    spec_path: str, kind: str, packages: list[str]
) -> list[str]:
    """Append packages to a spec file where that can be done safely.

    Returns the packages that could not be added. A requirements file and a
    generated pyproject both have one obvious place to put a name; conda and
    pixi files vary enough that a wrong guess would break the environment,
    so those are left for the user.
    """
    if not packages:
        return []
    if not os.path.isfile(spec_path):
        return packages
    with open(spec_path) as f:
        text = f.read()
    missing = [p for p in packages if not _spec_lists_package(text, p)]
    if not missing:
        return []
    if kind in ("uv-venv", "venv"):
        if text and not text.endswith("\n"):
            text += "\n"
        text += "".join(f"{p}\n" for p in missing)
    elif kind == "uv":
        match = re.search(r"dependencies\s*=\s*\[", text)
        if match is None:
            return missing
        # Insert just after the opening bracket, one per line, matching
        # the layout uv itself writes.
        insert = "".join(f'\n    "{p}",' for p in missing)
        text = text[: match.end()] + insert + text[match.end() :]
    else:
        return missing
    with open(spec_path, "w") as f:
        f.write(text)
    return []


def _choose_environment(
    ck_info: dict[str, Any], requested: str | None
) -> tuple[str | None, dict[str, Any] | None]:
    envs = ck_info.get("environments") or {}
    if requested is not None:
        if requested not in envs:
            raise HTTPException(404, f"Environment '{requested}' not found")
        return requested, envs[requested]
    for kind in PYTHON_ENV_KINDS:
        for name, env in envs.items():
            if isinstance(env, dict) and env.get("kind") == kind:
                return name, env
    return None, None


def _create_python_env(
    wdir: str, packages: list[str]
) -> tuple[str, dict[str, Any]]:
    """Write a `py` environment for the stage to run in.

    uv is the default. When the repo already has a pyproject.toml that
    isn't ours, a requirements file under .calkit/envs keeps out of its way.
    """
    if not os.path.isfile(os.path.join(wdir, "pyproject.toml")):
        spec_path = "pyproject.toml"
        deps = "".join(f'\n    "{p}",' for p in packages)
        content = (
            "[project]\n"
            'name = "py"\n'
            'version = "0.1.0"\n'
            'requires-python = ">=3.13"\n'
            f"dependencies = [{deps}{chr(10) if packages else ''}]\n"
        )
        env = {"kind": "uv", "path": spec_path}
    else:
        spec_path = ".calkit/envs/py/requirements.txt"
        content = "".join(f"{p}\n" for p in packages)
        env = {
            "kind": "uv-venv",
            "path": spec_path,
            "python": "3.13",
            "prefix": ".calkit/envs/py/.venv",
        }
    full = os.path.join(wdir, spec_path)
    os.makedirs(os.path.dirname(full) or wdir, exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    return spec_path, env


@router.post("/projects/{owner_name}/{project_name}/figures/script")
def post_project_figure_script(
    owner_name: str,
    project_name: str,
    req: FigureScriptPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> FigureScriptResult:
    """Commit a figure editor script as a stage that produces the figure.

    One commit carries the script, the stage, the figure entry, and the
    environment (created or amended), so the repo never holds a figure
    that points at a stage that doesn't exist yet.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    figure_path = _clean_rel_path(req.figure_path, "figure")
    script_path = _clean_rel_path(req.script_path, "script")
    inputs = [_clean_rel_path(p, "input") for p in req.inputs]
    if not figure_path.lower().endswith(FIGURE_SUFFIXES):
        raise HTTPException(
            422, f"Figure path should end in one of {FIGURE_SUFFIXES}"
        )
    if not script_path.endswith(".py"):
        raise HTTPException(422, "Script path should end in .py")
    if not req.script_content.strip():
        raise HTTPException(422, "Script is empty")
    if not req.title.strip():
        raise HTTPException(422, "A title is required")
    packages = sorted({p.strip() for p in req.packages if p.strip()})
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    wdir = str(repo.working_dir)
    ck_info = get_ck_info_from_repo(repo=repo)
    pipeline = ck_info.get("pipeline") or {}
    stages = pipeline.get("stages") or {}
    editing = None
    if req.stage is not None:
        editing = stages.get(req.stage)
        if editing is None:
            raise HTTPException(404, f"Stage '{req.stage}' not found")
        if editing.get("kind") != "python-script":
            raise HTTPException(
                400, f"Stage '{req.stage}' is not a Python script stage"
            )
    # Another stage already writing this path would make the pipeline
    # ambiguous about where the figure comes from, unless that's the stage
    # being edited.
    for name, stage in stages.items():
        for out in stage.get("outputs") or []:
            out_path = out.get("path") if isinstance(out, dict) else out
            if out_path == figure_path and name != req.stage:
                raise HTTPException(
                    400,
                    f"Stage '{name}' already produces {figure_path}; "
                    "edit that stage or choose another path",
                )
    # Environment: the one asked for; when editing, the stage's own unless
    # asked otherwise (a stage may run in a Docker image with Python in it,
    # which is nothing to replace with a fresh venv); else the project's
    # Python one, or a new one
    requested_env = req.environment
    if requested_env is None and editing is not None:
        requested_env = editing.get("environment")
    env_name, env = _choose_environment(ck_info, requested_env)
    env_created = False
    packages_missing: list[str] = []
    if env_name is None or env is None:
        env_name = "py"
        if env_name in (ck_info.get("environments") or {}):
            raise HTTPException(
                400,
                "Environment 'py' exists but isn't a Python kind; pick "
                "an environment explicitly",
            )
        spec_path, env = _create_python_env(wdir, packages)
        ck_info.setdefault("environments", {})[env_name] = env
        repo.git.add(spec_path)
        env_created = True
    else:
        spec_rel = env.get("path")
        if spec_rel:
            spec_full = os.path.join(wdir, spec_rel)
            packages_missing = _add_packages_to_spec(
                spec_full, str(env.get("kind")), packages
            )
            if os.path.isfile(spec_full):
                repo.git.add(spec_rel)
        else:
            packages_missing = packages
    # Script
    script_full = os.path.join(wdir, script_path)
    os.makedirs(os.path.dirname(script_full) or wdir, exist_ok=True)
    content = format_python(req.script_content)
    if not content.endswith("\n"):
        content += "\n"
    with open(script_full, "w") as f:
        f.write(content)
    repo.git.add(script_path)
    if editing is not None and req.stage is not None:
        # Editing: the stage keeps its name and whatever else it declares;
        # only what the figure editor owns changes
        stage_name = req.stage
        stage_map: dict[str, Any] = dict(editing)
        stage_map["script_path"] = script_path
        stage_map["environment"] = env_name
        if inputs:
            stage_map["inputs"] = inputs
        else:
            stage_map.pop("inputs", None)
        outs = list(stage_map.get("outputs") or [])
        if not any(
            (o.get("path") if isinstance(o, dict) else o) == figure_path
            for o in outs
        ):
            outs.append(figure_path)
        stage_map["outputs"] = outs
    else:
        # Creating: named after the figure and kept unique
        stem = posixpath.splitext(posixpath.basename(figure_path))[0]
        base = f"plot-{_slug(stem)}"
        stage_name = base
        n = 2
        while stage_name in stages:
            stage_name = f"{base}-{n}"
            n += 1
        stage_map = {
            "kind": "python-script",
            "script_path": script_path,
            "environment": env_name,
        }
        if inputs:
            stage_map["inputs"] = inputs
        stage_map["outputs"] = [figure_path]
    _validate_ck_stage(stage_map, stage_name)
    stages[stage_name] = stage_map
    pipeline["stages"] = stages
    ck_info["pipeline"] = pipeline
    # Figure entry: update in place if the path is already declared
    figures = ck_info.get("figures") or []
    entry = {
        "path": figure_path,
        "title": req.title.strip(),
        "description": (req.description or "").strip() or None,
        "stage": stage_name,
    }
    entry = {k: v for k, v in entry.items() if v is not None}
    for existing in figures:
        if isinstance(existing, dict) and existing.get("path") == figure_path:
            existing.update(entry)
            break
    else:
        figures.append(entry)
    ck_info["figures"] = figures
    with open(os.path.join(wdir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    # The project page reads the committed dvc.yaml, so the stage has to be
    # compiled into it here rather than waiting for the next `calkit run`.
    try:
        calkit.pipeline.to_dvc(ck_info=ck_info, wdir=wdir, write=True)
    except Exception as e:
        repo.git.checkout("--", ".")
        repo.git.clean("-fd")
        raise HTTPException(422, f"Could not compile the pipeline: {e}")
    repo.git.add("-A")
    message = req.message or (
        f"Update stage {stage_name} producing {figure_path}"
        if editing is not None
        else f"Add stage {stage_name} to produce {figure_path}"
    )
    repo.git.commit(["-m", message])
    repo.git.push(["origin", repo.active_branch.name])
    record_project_update(project, repo, session)
    mixpanel.user_saved_figure_script(
        user=current_user,
        project=project,
        env_created=env_created,
        n_inputs=len(inputs),
        n_packages=len(packages),
    )
    return FigureScriptResult(
        figure=Figure(
            path=figure_path,
            title=entry["title"],
            description=entry.get("description"),
            stage=stage_name,
        ),
        stage_name=stage_name,
        environment=env_name,
        environment_created=env_created,
        packages_missing=packages_missing,
        script_content=content,
    )
