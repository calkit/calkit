"""Routes for managing project pipelines.

Map-paths stages copy project paths to where something expects them.
A file or directory often needs to be somewhere other than where it lives,
e.g., a paper wants figures from the root ``figures`` directory under its
own, where LaTeX can find them without ``../``. A symlink would do that on
one machine, but doesn't survive Git on every platform; a map-paths stage
is the reproducible, cross-platform stand-in, making the copy part of the
pipeline so it's always current and any stage that reads it can depend on
it.

A stage can also be made from a script, as ``calkit xr`` makes one locally,
e.g., for a figure a paper includes that nothing in the pipeline produces.
"""

import base64
import binascii
import json
import os
import re
import subprocess
import tempfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import requests
from fastapi import APIRouter, HTTPException
from git import GitCommandError
from pydantic import BaseModel, Field

import app.cache
import app.github
import app.projects
import calkit.export
import calkit.latex
import calkit.pipeline
import calkit.provenance
import calkit.resources
from app.api.deps import CurrentUser, SessionDep
from app.api.routes.projects.core import (
    DEFAULT_REPO_TTL,
    STAGE_NAME_RE,
    _dump_ck_stage_map,
    _github_token_for_repo,
    _inside,
    _validate_ck_stage,
)
from app.api.routes.projects.figures import _clean_rel_path, _slug
from app.config import settings
from app.core import logger, ryaml
from app.dvc import run_dvc_command
from app.git import (
    _make_git_auth_env,
    get_ck_info_from_repo,
    get_default_branch,
    get_repo,
    get_repo_tree_for_ref,
    push_and_expire,
    record_project_update,
)
from app.models import PipelineStage
from app.storage import get_object_fs, make_data_fpath, remove_gcs_content_type
from calkit.models.pipeline import MapPathsKind, MapPathsStage

router = APIRouter()


class MapPathEntry(BaseModel):
    """One copy to add, as ``MapPathsStage.mapping_from`` takes it.

    The kind is worked out from what ``src`` is when not given, which the
    calkit mapping models can't do on their own since they each fix one.
    """

    src: str
    dest: str
    kind: MapPathsKind | None = None


class MapPathsPost(BaseModel):
    paths: list[MapPathEntry] = Field(min_length=1)
    # The map-paths stage to add to, created if missing; defaults to
    # ``map-paths-<dir>`` for the directory the copies land in (the
    # paper's), which is a name the editor can find again to PUT to
    stage_name: str | None = None
    # A stage that should read the copies, typically the publication's
    # build stage; it gets the map-paths stage's outputs as an input
    target_stage: str | None = None
    message: str | None = None


def _default_stage_name(target: dict[str, Any] | None, first_dest: str) -> str:
    """``map-paths-<dir>``, for the directory the copies go into.

    A LaTeX target names its directory through its ``target_path``; failing
    that, the first destination's top-level directory stands in.
    """
    target_path = str((target or {}).get("target_path") or "")
    paper_dir = os.path.dirname(target_path) if target_path else ""
    if not paper_dir:
        paper_dir = first_dest.strip("/").split("/")[0]
    return f"map-paths-{os.path.basename(paper_dir) or 'root'}"


@router.post("/projects/{owner_name}/{project_name}/pipeline/map-paths")
def post_project_map_paths(
    owner_name: str,
    project_name: str,
    req: MapPathsPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> PipelineStage:
    """Add copies to a map-paths stage, creating the stage if needed.

    The stage is committed to calkit.yaml and dvc.yaml is recompiled, so
    the next run makes the copies; when a target stage is named, it now
    depends on them.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    wdir = str(repo.working_dir)
    ck_info = get_ck_info_from_repo(repo=repo)
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    legacy_target = _legacy_target(stages, req.target_stage, wdir)
    stage_name = req.stage_name or _default_stage_name(
        stages.get(req.target_stage or ""), req.paths[0].dest
    )
    if not STAGE_NAME_RE.fullmatch(stage_name):
        raise HTTPException(422, f"'{stage_name}' is not a valid stage name")
    stage = stages.get(stage_name)
    if stage is None:
        stage = {"kind": "map-paths", "paths": []}
    elif stage.get("kind") != "map-paths":
        raise HTTPException(
            409, f"Stage '{stage_name}' exists and is not a map-paths stage"
        )
    existing = stage.setdefault("paths", [])
    # What's in the project, for telling a directory from a file: the
    # checkout for Git-tracked paths, DVC's outputs for the rest
    tree = get_repo_tree_for_ref(repo, None)
    dvc_outs = app.projects.dvc_outputs_from_tree(project=project, tree=tree)
    for entry in req.paths:
        src = _clean_rel_path(entry.src, "source path")
        dest = _clean_rel_path(entry.dest.rstrip("/"), "destination path")
        if src == dest:
            raise HTTPException(422, f"'{src}' would be copied onto itself")
        full = os.path.join(wdir, src)
        if os.path.isdir(full):
            is_dir = True
        elif os.path.isfile(full):
            is_dir = False
        elif src in dvc_outs:
            is_dir = str(dvc_outs[src].get("md5") or "").endswith(".dir")
        else:
            raise HTTPException(404, f"'{src}' is not in the project")
        try:
            mapping = MapPathsStage.mapping_from(
                src,
                # A trailing slash is what asks for a copy into a directory
                dest + ("/" if entry.dest.endswith("/") else ""),
                kind=entry.kind,
                is_dir=is_dir,
            )
        except ValueError as e:
            raise HTTPException(422, str(e))
        if any(
            p.get("src") == src and p.get("dest") == dest for p in existing
        ):
            continue
        existing.append(mapping.model_dump())
    _validate_ck_stage(stage, stage_name)
    stages[stage_name] = stage
    if req.target_stage is not None and legacy_target is None:
        target = stages[req.target_stage]
        inputs = target.setdefault("inputs", [])
        link = {"from_stage_outputs": stage_name}
        if link not in inputs:
            inputs.append(link)
        _validate_ck_stage(target, req.target_stage)
    ck_info.setdefault("pipeline", {})["stages"] = stages
    copied = ", ".join(p.src for p in req.paths)
    _commit_pipeline(
        project,
        session,
        repo,
        ck_info,
        legacy_target,
        [p["dest"] for p in existing],
        [],
        req.message or f"Copy {copied} in stage {stage_name}",
    )
    return PipelineStage(name=stage_name, yaml=_dump_ck_stage_map(stage))


@router.delete("/projects/{owner_name}/{project_name}/pipeline/map-paths")
def delete_project_map_paths(
    owner_name: str,
    project_name: str,
    stage_name: str,
    src: str,
    dest: str,
    current_user: CurrentUser,
    session: SessionDep,
    target_stage: str | None = None,
) -> PipelineStage:
    """Take one copy out of a map-paths stage.

    The last copy takes the stage with it, and any stage that read from it
    stops doing so, so nothing is left pointing at a stage that's gone.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    ck_info = get_ck_info_from_repo(repo=repo)
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    stage = stages.get(stage_name)
    if stage is None or stage.get("kind") != "map-paths":
        raise HTTPException(404, f"Map-paths stage '{stage_name}' not found")
    paths = stage.get("paths") or []
    kept = [
        p for p in paths if not (p.get("src") == src and p.get("dest") == dest)
    ]
    if len(kept) == len(paths):
        raise HTTPException(404, f"'{src}' is not copied by '{stage_name}'")
    legacy_target = _legacy_target(stages, target_stage, str(repo.working_dir))
    if kept:
        stage["paths"] = kept
        _validate_ck_stage(stage, stage_name)
    else:
        del stages[stage_name]
        link = {"from_stage_outputs": stage_name}
        for other in stages.values():
            inputs = other.get("inputs")
            if isinstance(inputs, list) and link in inputs:
                inputs.remove(link)
    ck_info.setdefault("pipeline", {})["stages"] = stages
    _commit_pipeline(
        project,
        session,
        repo,
        ck_info,
        legacy_target,
        [p["dest"] for p in kept],
        [dest],
        f"Stop copying {src} in stage {stage_name}",
    )
    return PipelineStage(
        name=stage_name, yaml=_dump_ck_stage_map(stage) if kept else ""
    )


def _legacy_target(
    stages: dict[str, Any], target_stage: str | None, wdir: str
) -> str | None:
    """A target stage that lives only in dvc.yaml, or None.

    Older projects define their pipeline in dvc.yaml alone. ``to_dvc``
    carries such stages over untouched, so their deps have to be edited
    there directly for the copies to count as inputs.
    """
    if target_stage is None or target_stage in stages:
        return None
    dvc_path = os.path.join(wdir, "dvc.yaml")
    if not os.path.isfile(dvc_path):
        raise HTTPException(404, f"Stage '{target_stage}' not found")
    with open(dvc_path) as f:
        dvc_stages = (ryaml.load(f) or {}).get("stages") or {}
    if target_stage not in dvc_stages:
        raise HTTPException(404, f"Stage '{target_stage}' not found")
    return target_stage


def _commit_pipeline(
    project: Any,
    session: Any,
    repo: Any,
    ck_info: dict[str, Any],
    legacy_target: str | None,
    dests: list[str],
    removed: list[str],
    message: str,
) -> None:
    """Write calkit.yaml, recompile dvc.yaml, commit, and push.

    For a legacy target, the copies' destinations become that stage's deps
    in dvc.yaml after compiling (and a removed one leaves them), since
    ``to_dvc`` carries the stage over rather than compiling it.
    """
    wdir = str(repo.working_dir)
    ryaml.dump(ck_info, Path(wdir, "calkit.yaml"))
    repo.git.add("calkit.yaml")
    try:
        calkit.pipeline.to_dvc(ck_info=ck_info, wdir=wdir, write=True)
        if legacy_target is not None:
            dvc_path = os.path.join(wdir, "dvc.yaml")
            with open(dvc_path) as f:
                dvc_yaml = ryaml.load(f) or {}
            target = dvc_yaml["stages"][legacy_target]
            deps = [d for d in (target.get("deps") or []) if d not in removed]
            target["deps"] = deps + [d for d in dests if d not in deps]
            ryaml.dump(dvc_yaml, Path(dvc_path))
        repo.git.add("-A")
    except Exception as e:
        repo.git.checkout("--", ".")
        repo.git.clean("-fd")
        raise HTTPException(422, f"Could not compile the pipeline: {e}")
    if repo.is_dirty():
        repo.git.commit(["-m", message])
        push_and_expire(project, repo)
        record_project_update(project, repo, session)


# What calkit xr makes a script stage from, by extension
SCRIPT_EXTS = (".py", ".r", ".jl", ".m", ".ipynb", ".sh")
MAX_SCRIPT_BYTES = 1_000_000


class StageFromScriptOrNotebookPost(BaseModel):
    # Where the script is in the project, or goes, when it's uploaded
    script_path: str
    # An uploaded script, base64-encoded
    content: str | None = None
    # What a document shows, e.g., a figure a paper includes, and which of
    # the script's outputs that is, when the script writes it elsewhere
    shows: str | None = None
    produces: str | None = None
    # Without it, nothing is written, so the user can see what would be
    save: bool = False


class StageFromScriptOrNotebookResponse(BaseModel):
    stage_name: str
    stage_yaml: str
    environment: str
    environment_is_new: bool
    # A spec file written for a new environment, e.g., a pyproject.toml
    # listing the packages the script imports
    environment_spec_path: str | None = None
    environment_spec_content: str | None = None
    dependencies: list[str] = []
    inputs: list[str] = []
    outputs: list[str] = []
    # Those found by reading the script, or already declared by its stage,
    # rather than only added because a document shows them
    found_outputs: list[str] = []
    # Inputs that aren't in the project and that no stage produces
    missing_inputs: list[str] = []
    # Which output is what the document shows, and the documents changed
    # to show it from there with \ckfigure when that's a different path
    produces: str | None = None
    included_in: list[str] = []
    saved: bool = False
    git_repo_url: str


@router.post(
    "/projects/{owner_name}/{project_name}/pipeline/stages/from-script-or-notebook"
)
def post_project_stage_from_script_or_notebook(
    owner_name: str,
    project_name: str,
    req: StageFromScriptOrNotebookPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> StageFromScriptOrNotebookResponse:
    """Make a stage from a script, uploaded or already in the project.

    The script is read, not run, as ``calkit xr --dry-run`` reads it: its
    environment from what it imports, and its inputs and outputs from the
    paths it opens. That happens in a checkout of its own, so an uploaded
    script isn't left in the project's clone before it's saved. With
    ``save``, the script, its environment, and the stage are committed,
    with each document that shows the output elsewhere changed to show it
    with ``\\ckfigure`` from where it's made.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    wdir = str(repo.working_dir)
    script_path = _clean_rel_path(req.script_path, "script")
    if not script_path.lower().endswith(SCRIPT_EXTS):
        raise HTTPException(
            422,
            "Scripts can be Python, R, Julia, MATLAB, shell, or Jupyter "
            "notebooks",
        )
    content = None
    if req.content is not None:
        try:
            content = base64.b64decode(req.content, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "Script content isn't valid base64")
        if len(content) > MAX_SCRIPT_BYTES:
            raise HTTPException(413, "Script is too large")
    elif not os.path.isfile(os.path.join(wdir, script_path)):
        raise HTTPException(404, f"'{script_path}' is not in the project")
    # An upload never replaces a different file already there
    existing_path = os.path.join(wdir, script_path)
    if content is not None and not _inside(wdir, existing_path):
        raise HTTPException(422, f"'{script_path}' leads outside the project")
    if content is not None and os.path.isfile(existing_path):
        with open(existing_path, "rb") as fb:
            if fb.read() != content:
                raise HTTPException(
                    409,
                    f"'{script_path}' is already in the project; pick it "
                    "without uploading, or upload under another name",
                )
    # Read in a checkout of its own, discarded after
    scan_dir = tempfile.mkdtemp(prefix="calkit-xr-")
    os.rmdir(scan_dir)
    repo.git.worktree("add", "--detach", scan_dir, "HEAD")
    try:
        if content is not None:
            dest = os.path.join(scan_dir, script_path)
            if not _inside(scan_dir, dest):
                raise HTTPException(
                    422, f"'{script_path}' leads outside the project"
                )
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fb:
                fb.write(content)
        try:
            result = subprocess.run(
                ["calkit", "xr", "--dry-run", "--json", script_path],
                cwd=scan_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, f"Reading '{script_path}' took too long")
    finally:
        repo.git.worktree("remove", "--force", scan_dir)
    # Anything printed before the JSON is xr saying what it chose
    start = result.stdout.find("\n{")
    if result.returncode != 0 or not result.stdout.strip():
        lines = [x.strip() for x in result.stderr.splitlines() if x.strip()]
        detail = lines[-1].removeprefix("Error: ") if lines else ""
        logger.info(f"xr --dry-run on {script_path} failed: {result.stderr}")
        raise HTTPException(422, detail or f"Can't read '{script_path}'")
    detected = json.loads(
        result.stdout
        if result.stdout.startswith("{")
        else result.stdout[start + 1 :]
    )
    env = detected["environment"]
    stage_name = detected["stage"]["name"]
    stage = detected["stage"]["stage"]
    ck_info = get_ck_info_from_repo(repo=repo)
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    # A stage that already runs this script keeps what it declares, with
    # anything newly found added
    existing_stage = stages.get(stage_name)
    if isinstance(existing_stage, dict):
        merged = dict(existing_stage)
        for field in ("outputs", "inputs"):
            items = list(existing_stage.get(field) or [])
            known = {
                i.get("path") if isinstance(i, dict) else i for i in items
            }
            items += [
                i
                for i in stage.get(field) or []
                if (i["path"] if isinstance(i, dict) else i) not in known
            ]
            if items:
                merged[field] = items
        stage = merged
    outputs = [
        o["path"] if isinstance(o, dict) else o
        for o in stage.get("outputs") or []
    ]
    found_outputs = list(outputs)
    # Env vars, schedules, and other stages' outputs aren't paths
    inputs = [
        i if isinstance(i, str) else i["path"]
        for i in stage.get("inputs") or []
        if isinstance(i, str) or "path" in i
    ]
    tree = get_repo_tree_for_ref(repo, None)
    dvc_outs = app.projects.dvc_outputs_from_tree(project=project, tree=tree)
    missing = [
        i
        for i in inputs
        if not os.path.exists(os.path.join(wdir, i))
        and i not in dvc_outs
        and calkit.pipeline.get_stage_for_output(i, ck_info) is None
    ]

    def include(shown: str, path: str) -> dict[str, str]:
        # The new text of each document file that would show it from path
        documents = [
            s["target_path"]
            for s in stages.values()
            if isinstance(s, dict)
            and s.get("kind") == "latex"
            and s.get("target_path")
        ]
        for folder in ck_info.get("overleaf_sync") or {}:
            if os.path.isdir(os.path.join(wdir, folder)):
                documents += [
                    os.path.relpath(d, wdir)
                    for d in calkit.latex.root_documents(
                        os.path.join(wdir, folder)
                    )
                ]
        changed: dict[str, str] = {}
        for document in dict.fromkeys(documents):
            changed.update(
                calkit.latex.include_figure(document, shown, path, wdir=wdir)
            )
        return changed

    # The output the document shows: the same path, or the one the user
    # picked, or else the only one with the same file name
    shows = _clean_rel_path(req.shows, "shown") if req.shows else None
    produces = None
    if req.produces is not None:
        produces = _clean_rel_path(req.produces, "output")
        if produces not in outputs and produces != shows:
            raise HTTPException(
                422, f"'{script_path}' doesn't write '{produces}'"
            )
    elif shows in outputs:
        produces = shows
    elif shows is not None:
        same_name = [
            o
            for o in outputs
            if os.path.basename(o) == os.path.basename(shows)
        ]
        # Only worth guessing if a document includes it, so it can show it
        # from there instead
        if len(same_name) == 1 and include(shows, same_name[0]):
            produces = same_name[0]
    # What the document shows is what the stage makes, so if the script
    # isn't found writing it anywhere, it writes it there
    if shows is not None and produces is None:
        produces = shows
    if produces is not None and produces not in outputs:
        tracked = bool(repo.git.ls_files("--", produces).strip())
        stage.setdefault("outputs", []).append(
            {"path": produces, "storage": "git"} if tracked else produces
        )
        outputs.append(produces)
    included: dict[str, str] = {}
    if shows is not None and produces is not None and produces != shows:
        included = include(shows, produces)
        if not included:
            raise HTTPException(
                422,
                f"No document includes '{shows}' to show it from "
                f"'{produces}' instead",
            )
    out = StageFromScriptOrNotebookResponse(
        stage_name=stage_name,
        stage_yaml=_dump_ck_stage_map(stage),
        environment=env["name"],
        environment_is_new=not env["exists"],
        environment_spec_path=(
            env["spec_path"] if env["created_from_dependencies"] else None
        ),
        environment_spec_content=(
            env["spec_content"] if env["created_from_dependencies"] else None
        ),
        dependencies=env.get("dependencies") or [],
        inputs=inputs,
        outputs=outputs,
        found_outputs=found_outputs,
        missing_inputs=missing,
        produces=produces,
        included_in=sorted(included),
        git_repo_url=project.git_repo_url,
    )
    if not req.save:
        return out
    # Nothing is written through a symlink that leads out of the project
    writes = [script_path] if content is not None else []
    if out.environment_spec_path:
        writes.append(
            _clean_rel_path(out.environment_spec_path, "environment")
        )
    for path in writes + list(included):
        if not _inside(wdir, os.path.join(wdir, path)):
            raise HTTPException(422, f"'{path}' leads outside the project")
    # Written as xr writes them, then committed with the pipeline
    if content is not None:
        dest = os.path.join(wdir, script_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fb:
            fb.write(content)
    if out.environment_spec_path and out.environment_spec_content is not None:
        spec_path = os.path.join(
            wdir, _clean_rel_path(out.environment_spec_path, "environment")
        )
        os.makedirs(os.path.dirname(spec_path) or wdir, exist_ok=True)
        with open(spec_path, "w") as f:
            f.write(out.environment_spec_content)
    if out.environment_is_new:
        ck_info.setdefault("environments", {})[env["name"]] = env["env"]
    _validate_ck_stage(stage, stage_name)
    stages[stage_name] = stage
    for path, text in included.items():
        with open(os.path.join(wdir, path), "w") as f:
            f.write(text)
    ck_info.setdefault("pipeline", {})["stages"] = stages
    _commit_pipeline(
        project,
        session,
        repo,
        ck_info,
        None,
        [],
        [],
        f"Add stage {stage_name} for {script_path}",
    )
    out.saved = True
    return out


MAX_FILE_BYTES = 500_000_000
# A file bigger than this is stored with DVC rather than in Git
FILE_GIT_MAX_BYTES = 1_000_000


class StageFile(BaseModel):
    """A file a new stage needs, e.g., a script or the file a figure is
    exported from."""

    path: str
    # Uploaded, base64-encoded; without it, the file is already in the
    # project
    content: str | None = None
    # Recorded as created by whoever adds it, e.g., a Photoshop file
    created_by_me: bool = False


class StagePost(BaseModel):
    # A taken name gets a number appended; without one, it's named after
    # its first output
    name: str | None = None
    # As written under the stage's name in calkit.yaml
    stage: dict[str, Any]
    files: list[StageFile] = []
    message: str | None = None


@router.post("/projects/{owner_name}/{project_name}/pipeline/stages")
def post_project_pipeline_stage(
    owner_name: str,
    project_name: str,
    req: StagePost,
    current_user: CurrentUser,
    session: SessionDep,
) -> PipelineStage:
    """Add a stage, with any files it needs, in one commit.

    An upload never replaces a different file already there, and one too
    big for Git is stored with DVC. An output another stage already makes
    is refused, and one already in Git stays there.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    wdir = str(repo.working_dir)
    ck_info = get_ck_info_from_repo(repo=repo)
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    stage = dict(req.stage)
    # Outputs are made by one stage only, and one already in Git can't
    # move to DVC
    outputs = []
    for out in stage.get("outputs") or []:
        path = _clean_rel_path(
            out["path"] if isinstance(out, dict) else str(out), "output"
        )
        producer = calkit.pipeline.get_stage_for_output(path, ck_info)
        if producer is not None:
            raise HTTPException(409, f"'{path}' is made by stage '{producer}'")
        if not isinstance(out, dict):
            tracked = repo.git.ls_files("--", path).strip()
            out = {"path": path, "storage": "git"} if tracked else path
        outputs.append(out)
    if outputs:
        stage["outputs"] = outputs
    first = outputs[0] if outputs else None
    first_path = first["path"] if isinstance(first, dict) else first
    base_name = req.name or (
        _slug(os.path.splitext(os.path.basename(first_path))[0])
        if first_path
        else "stage"
    )
    if not STAGE_NAME_RE.fullmatch(base_name or ""):
        raise HTTPException(422, f"Invalid stage name: {req.name!r}")
    stage_name = base_name
    n = 2
    while stage_name in stages:
        stage_name = f"{base_name}-{n}"
        n += 1
    _validate_ck_stage(stage, stage_name)
    # Files are all checked before any is written
    uploads: list[tuple[str, bytes]] = []
    created: list[str] = []
    for file in req.files:
        path = _clean_rel_path(file.path, "file")
        full = os.path.join(wdir, path)
        if not _inside(wdir, full):
            raise HTTPException(422, f"'{path}' leads outside the project")
        if file.created_by_me:
            if not calkit.provenance.can_be_created_by_person(path):
                raise HTTPException(
                    422,
                    f"'{path}' is exported from something itself, so it "
                    "can't be created by a person; add the file it's made "
                    "from, e.g., a Photoshop file",
                )
            created.append(path)
        if file.content is None:
            if not (os.path.isfile(full) or os.path.isfile(full + ".dvc")):
                raise HTTPException(404, f"'{path}' is not in the project")
            continue
        try:
            content = base64.b64decode(file.content, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, f"Content of '{path}' isn't valid base64")
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(413, f"'{path}' is too large")
        if os.path.isfile(full):
            with open(full, "rb") as fb:
                if fb.read() != content:
                    raise HTTPException(
                        409,
                        f"'{path}' is already in the project; pick it "
                        "without uploading, or upload under another name",
                    )
        uploads.append((path, content))
    for path, content in uploads:
        full = os.path.join(wdir, path)
        os.makedirs(os.path.dirname(full) or wdir, exist_ok=True)
        with open(full, "wb") as fb:
            fb.write(content)
        if len(content) <= FILE_GIT_MAX_BYTES:
            continue
        if not os.path.isdir(os.path.join(wdir, ".dvc")):
            run_dvc_command(["init"], wdir=wdir, check=True)
        run_dvc_command(["add", path], wdir=wdir, check=True)
        # Put where the hub's DVC remote serves it, by its hash
        with open(full + ".dvc") as f:
            md5 = (ryaml.load(f) or {})["outs"][0]["md5"]
        fpath = make_data_fpath(
            owner_name=project.owner_account_name,
            project_name=project.name,
            idx=md5[:2],
            md5=md5[2:],
        )
        with get_object_fs().open(fpath, "wb") as f_out:
            f_out.write(content)
        if settings.ENVIRONMENT != "local":
            remove_gcs_content_type(fpath)
    # What someone made is theirs, unless something already says otherwise
    person = {"email": current_user.email}
    if current_user.full_name:
        person["name"] = current_user.full_name
    for path in created:
        entry = next(
            (
                e
                for items in ck_info.values()
                if isinstance(items, list)
                for e in items
                if isinstance(e, dict) and e.get("path") == path
            ),
            None,
        )
        if entry is None:
            ck_info.setdefault("misc", []).append(
                {"path": path, "created_by": [person]}
            )
        elif not (
            entry.get("created_by")
            or entry.get("imported_from")
            or entry.get("stage")
        ):
            entry["created_by"] = [person]
    stages[stage_name] = stage
    ck_info.setdefault("pipeline", {})["stages"] = stages
    _commit_pipeline(
        project,
        session,
        repo,
        ck_info,
        None,
        [],
        [],
        req.message or f"Add stage {stage_name}",
    )
    return PipelineStage(name=stage_name, yaml=_dump_ck_stage_map(stage))


class ExportStagePost(BaseModel):
    # The file it's exported from, and the figure it's exported to
    source: str
    output: str
    # The app a person exports it with, e.g., Photoshop
    app: str | None = None
    files: list[StageFile] = []
    # False to see the stage without adding it
    save: bool = True


class ExportStage(BaseModel):
    name: str
    stage: dict[str, Any]
    # The app that exports it as the pipeline runs, if one does
    exported_by: str | None = None
    saved: bool = False


@router.post("/projects/{owner_name}/{project_name}/pipeline/stages/export")
def post_project_pipeline_export_stage(
    owner_name: str,
    project_name: str,
    req: ExportStagePost,
    current_user: CurrentUser,
    session: SessionDep,
) -> ExportStage:
    """Add the stage that exports a figure from the file it's drawn in.

    An app that can do it as the pipeline runs does, unless the person
    named another; otherwise it's a manual step.
    """
    source = _clean_rel_path(req.source, "source")
    output = _clean_rel_path(req.output, "output")
    exporter = calkit.export.exporter_for(source, output, app=req.app)
    stage = calkit.export.export_stage(source, output, app=req.app)
    name = calkit.export.export_stage_name(output)
    if not req.save:
        return ExportStage(
            name=name,
            stage=stage,
            exported_by=exporter.app if exporter else None,
        )
    saved = post_project_pipeline_stage(
        owner_name=owner_name,
        project_name=project_name,
        req=StagePost(
            name=name,
            stage=stage,
            files=req.files,
            message=(
                f"Export {output} from {source}"
                + (f" with {exporter.app}" if exporter else " manually")
            ),
        ),
        current_user=current_user,
        session=session,
    )
    return ExportStage(
        name=saved.name,
        stage=stage,
        exported_by=exporter.app if exporter else None,
        saved=True,
    )


# Runs listed, newest first, across a project's workflows
MAX_PIPELINE_RUNS = 10
# How long GitHub's lists of runs are reused, so everyone watching a project
# shares one request
RUNS_CACHE_TTL_S = 10
# Runs of the pipeline on the default branch, not, e.g., a pull request's
RUN_EVENTS = ("workflow_dispatch", "push")
RunStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]


class PipelineRun(BaseModel):
    """A run of the pipeline, wherever it ran."""

    where: Literal["github-actions"] = "github-actions"
    # Unknown for a run just started, until GitHub lists it
    id: str | None = None
    status: RunStatus
    started_at: str | None = None
    url: str | None = None
    commit: str | None = None
    branch: str | None = None
    started_by: str | None = None
    # The GitHub Actions workflow it ran in, by file name
    workflow: str | None = None


class PipelineRuns(BaseModel):
    runs: list[PipelineRun] = []
    # The workflow that starting a run on GitHub Actions uses, if the project
    # has one
    github_workflow: str | None = None
    # Whether it can be started from here, and if not, why
    can_start: bool = False
    cannot_start_reason: str | None = None


def _runs_cache_key(github_repo: str, fname: str, branch: str) -> str:
    return app.cache.make_key("pipeline-runs", github_repo, fname, branch)


@router.get("/projects/{owner_name}/{project_name}/pipeline/runs")
def get_project_pipeline_runs(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> PipelineRuns:
    """Recent runs of the pipeline on the default branch, and whether one
    can be started here.

    Only runs on GitHub Actions so far, by every workflow that runs the
    Calkit action, when started or pushed.
    """

    def github_run(run: dict[str, Any], workflow: str) -> PipelineRun:
        status = run.get("status")
        conclusion = run.get("conclusion")
        state: RunStatus
        if status == "in_progress":
            state = "running"
        elif status != "completed":
            state = "queued"
        elif conclusion == "success":
            state = "succeeded"
        elif conclusion in ("cancelled", "skipped", "stale", "neutral"):
            state = "canceled"
        else:
            state = "failed"
        return PipelineRun(
            id=str(run.get("id")),
            status=state,
            started_at=run.get("run_started_at") or run.get("created_at"),
            url=run.get("html_url"),
            commit=run.get("head_sha"),
            branch=run.get("head_branch"),
            started_by=(run.get("triggering_actor") or {}).get("login"),
            workflow=workflow,
        )

    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    if not project.github_repo:
        return PipelineRuns(cannot_start_reason="This project isn't on GitHub")
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        read_only=True,
    )
    found = calkit.resources.find_run_workflows(str(repo.working_dir))
    if not found:
        # Starting it adds the workflow first
        return PipelineRuns(can_start=True)
    startable = [
        fname
        for fname, txt in found
        if calkit.resources.can_start_workflow(txt)
    ]
    token = _github_token_for_repo(
        session,
        current_user,
        project.github_repo,
        permissions={"actions": "read"},
    )
    if token is None:
        return PipelineRuns(cannot_start_reason="No GitHub access to its runs")
    branch = get_default_branch(repo)
    runs = []
    for fname, _ in found:
        key = _runs_cache_key(project.github_repo, fname, branch)
        listed = app.cache.get_json(key)
        if listed is None:
            try:
                resp = requests.get(
                    f"https://api.github.com/repos/{project.github_repo}"
                    f"/actions/workflows/{quote(fname, safe='')}/runs",
                    params={"per_page": MAX_PIPELINE_RUNS, "branch": branch},
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {token}",
                    },
                    timeout=10,
                )
            except requests.RequestException as e:
                logger.warning(f"Could not list runs of {fname}: {e}")
                continue
            if not resp.ok:
                logger.warning(
                    f"Could not list runs of {fname} for "
                    f"{project.github_repo}: {resp.status_code} {resp.text}"
                )
                continue
            listed = [
                github_run(r, workflow=fname).model_dump()
                for r in resp.json().get("workflow_runs", [])
                if r.get("event") in RUN_EVENTS
            ]
            app.cache.set_json(key, listed, ttl=RUNS_CACHE_TTL_S)
        runs += [PipelineRun.model_validate(r) for r in listed]
    # Newest first across workflows
    runs.sort(key=lambda run: run.started_at or "", reverse=True)
    names = ", ".join(fname for fname, _ in found)
    return PipelineRuns(
        runs=runs[:MAX_PIPELINE_RUNS],
        github_workflow=startable[0] if startable else found[0][0],
        can_start=bool(startable),
        cannot_start_reason=(
            None if startable else f"No workflow_dispatch trigger in {names}"
        ),
    )


@router.post("/projects/{owner_name}/{project_name}/pipeline/runs")
def post_project_pipeline_run(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> PipelineRun:
    """Start the pipeline on GitHub Actions, on the default branch.

    A project without a workflow that runs the Calkit action gets one that
    only runs when started, since every Overleaf sync is a push.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    if not project.github_repo:
        raise HTTPException(422, "This project isn't on GitHub")
    # Before anything's pushed, so a refusal leaves the project as it was
    token = _github_token_for_repo(
        session,
        current_user,
        project.github_repo,
        permissions={"actions": "write"},
    )
    if token is None:
        raise HTTPException(403, "No GitHub access to start a run")
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    wdir = str(repo.working_dir)
    branch = get_default_branch(repo)
    found = calkit.resources.find_run_workflows(wdir)
    if not found:
        rel_path = os.path.join(".github", "workflows", "run-calkit.yml")
        if not _inside(wdir, os.path.join(wdir, os.path.dirname(rel_path))):
            raise HTTPException(
                409, ".github/workflows links out of the project"
            )
        if os.path.lexists(os.path.join(wdir, rel_path)):
            raise HTTPException(
                409, f"{rel_path} doesn't run the Calkit action"
            )
        try:
            subprocess.check_call(
                [
                    "calkit",
                    "update",
                    "github-actions",
                    "--on-demand",
                    "--no-commit",
                ],
                cwd=wdir,
            )
            repo.git.add(rel_path)
            repo.git.commit(
                [rel_path, "-m", "Add a workflow that runs the pipeline"]
            )
            if current_user.account.github_name is None:
                # The App's usual token can't push workflows, so its holder
                # can't push one that reads the repo's secrets
                gh_owner, gh_repo = project.github_repo.split("/", 1)
                with repo.git.custom_environment(
                    **_make_git_auth_env(
                        app.github.get_app_installation_token(
                            gh_owner,
                            gh_repo,
                            permissions={
                                "contents": "write",
                                "workflows": "write",
                            },
                        )
                    )
                ):
                    push_and_expire(project, repo, branch)
            else:
                push_and_expire(project, repo, branch)
        except (
            subprocess.CalledProcessError,
            GitCommandError,
            HTTPException,
            app.github.GitHubAppNotConfigured,
        ) as e:
            repo.git.reset(["--hard", f"origin/{branch}"])
            repo.git.clean(["-fd"])
            logger.warning(
                f"Could not add a workflow to {project.github_repo}: {e}"
            )
            if isinstance(e, HTTPException) or (
                "without `workflows` permission" in str(e)
            ):
                raise HTTPException(
                    403,
                    "Calkit's GitHub App needs permission to add workflows "
                    "to add the one that runs the pipeline",
                )
            raise HTTPException(
                502, "Could not add the workflow that runs the pipeline"
            )
        record_project_update(project, repo, session)
        found = calkit.resources.find_run_workflows(wdir)
    startable = [
        fname
        for fname, txt in found
        if calkit.resources.can_start_workflow(txt)
    ]
    if not startable:
        names = ", ".join(fname for fname, _ in found)
        raise HTTPException(409, f"No workflow_dispatch trigger in {names}")
    fname = startable[0]
    try:
        resp = requests.post(
            f"https://api.github.com/repos/{project.github_repo}"
            f"/actions/workflows/{quote(fname, safe='')}/dispatches",
            json={"ref": branch},
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
            },
            timeout=10,
        )
    except requests.RequestException as e:
        raise HTTPException(502, f"Could not reach GitHub: {e}")
    if not resp.ok:
        logger.warning(
            f"Could not start {fname} for {project.github_repo}: "
            f"{resp.status_code} {resp.text}"
        )
        try:
            reason = resp.json().get("message") or resp.reason
        except ValueError:
            reason = resp.reason
        raise HTTPException(
            403 if resp.status_code in (403, 404) else 502,
            f"GitHub didn't start {fname}: {reason}",
        )
    # So the next listing has it as soon as GitHub does
    app.cache.delete(_runs_cache_key(project.github_repo, fname, branch))
    return PipelineRun(
        status="queued",
        started_at=datetime.now(timezone.utc).isoformat(),
        url=f"https://github.com/{project.github_repo}/actions/workflows/{fname}",
        branch=branch,
        started_by=current_user.github_username,
        workflow=fname,
    )


class PipelineRunStep(BaseModel):
    name: str
    status: str
    conclusion: str | None = None


class PipelineRunJob(BaseModel):
    name: str
    status: str
    conclusion: str | None = None
    steps: list[PipelineRunStep] = []
    # Only once the job finishes, since GitHub keeps it until then
    log: str | None = None
    # The start was cut, keeping the end, which is where failures are
    log_truncated: bool = False


class PipelineRunLogs(BaseModel):
    jobs: list[PipelineRunJob] = []


MAX_RUN_LOG_CHARS = 200_000
# Of a job's log, the end, which is where failures are, is all that's read
MAX_RUN_LOG_BYTES = 1_000_000
# Jobs whose logs are read, of those GitHub lists first
MAX_LOGGED_JOBS = 10
# A finished run's logs don't change, so they're kept this long
RUN_LOGS_CACHE_TTL_S = 24 * 3600
# GitHub's timestamp on every line, and its markers for folding sections
_LOG_TIMESTAMP_RE = re.compile(r"^﻿?\d{4}-\d\d-\d\dT[\d:.]+Z ?", re.M)
_LOG_GROUP_RE = re.compile(r"^##\[(group|endgroup)\]", re.M)


@router.get(
    "/projects/{owner_name}/{project_name}/pipeline/runs/{run_id}/logs"
)
def get_project_pipeline_run_logs(
    owner_name: str,
    project_name: str,
    run_id: int,
    current_user: CurrentUser,
    session: SessionDep,
) -> PipelineRunLogs:
    """A pipeline run's jobs, their steps, and each finished job's log.

    Only for runs of a workflow that runs the Calkit action.
    """

    def read_log(url: str) -> tuple[str, bool]:
        # Redirects to storage, which doesn't get the token, and only the
        # end is kept, without holding all of a huge log at once
        chunks: deque[bytes] = deque()
        kept = 0
        truncated = False
        with requests.get(
            url, headers=headers, timeout=20, stream=True
        ) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_content(64 * 1024):
                chunks.append(chunk)
                kept += len(chunk)
                while kept - len(chunks[0]) >= MAX_RUN_LOG_BYTES:
                    kept -= len(chunks.popleft())
                    truncated = True
        log = b"".join(chunks).decode("utf-8", errors="replace")
        log = _LOG_GROUP_RE.sub("", _LOG_TIMESTAMP_RE.sub("", log))
        if len(log) > MAX_RUN_LOG_CHARS:
            log = log[-MAX_RUN_LOG_CHARS:]
            truncated = True
        return log, truncated

    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    if not project.github_repo:
        raise HTTPException(422, "This project isn't on GitHub")
    cache_key = app.cache.make_key(
        "pipeline-run-logs", project.github_repo, str(run_id)
    )
    cached = app.cache.get_json(cache_key)
    if cached is not None:
        return PipelineRunLogs.model_validate(cached)
    token = _github_token_for_repo(
        session,
        current_user,
        project.github_repo,
        permissions={"actions": "read"},
    )
    if token is None:
        raise HTTPException(403, "No GitHub access to its runs")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    }
    base = f"https://api.github.com/repos/{project.github_repo}/actions"
    # Only the pipeline's runs, not those of the repo's other workflows
    try:
        resp = requests.get(
            f"{base}/runs/{run_id}", headers=headers, timeout=10
        )
    except requests.RequestException as e:
        raise HTTPException(502, f"Could not reach GitHub: {e}")
    if not resp.ok:
        raise HTTPException(
            404 if resp.status_code == 404 else 502,
            f"GitHub didn't find the run: {resp.reason}",
        )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        read_only=True,
    )
    workflows = {
        fname
        for fname, _ in calkit.resources.find_run_workflows(
            str(repo.working_dir)
        )
    }
    if os.path.basename(resp.json().get("path") or "") not in workflows:
        raise HTTPException(404, "Not a run of the pipeline")
    try:
        resp = requests.get(
            f"{base}/runs/{run_id}/jobs", headers=headers, timeout=10
        )
    except requests.RequestException as e:
        raise HTTPException(502, f"Could not reach GitHub: {e}")
    if not resp.ok:
        raise HTTPException(
            404 if resp.status_code == 404 else 502,
            f"GitHub didn't list the run's jobs: {resp.reason}",
        )
    jobs = []
    for i, job in enumerate(resp.json().get("jobs", [])):
        log = None
        truncated = False
        if job.get("status") == "completed" and i < MAX_LOGGED_JOBS:
            try:
                log, truncated = read_log(f"{base}/jobs/{job['id']}/logs")
            except requests.RequestException as e:
                logger.warning(
                    f"Could not get the log of job {job['id']}: {e}"
                )
        jobs.append(
            PipelineRunJob(
                name=job.get("name") or "",
                status=job.get("status") or "",
                conclusion=job.get("conclusion"),
                steps=[
                    PipelineRunStep(
                        name=step.get("name") or "",
                        status=step.get("status") or "",
                        conclusion=step.get("conclusion"),
                    )
                    for step in job.get("steps") or []
                ],
                log=log,
                log_truncated=truncated,
            )
        )
    out = PipelineRunLogs(jobs=jobs)
    if jobs and all(
        job.status == "completed" and job.log is not None for job in jobs
    ):
        app.cache.set_json(
            cache_key, out.model_dump(), ttl=RUN_LOGS_CACHE_TTL_S
        )
    return out
