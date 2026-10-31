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
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import app.projects
import calkit.gimp
import calkit.inkscape
import calkit.latex
import calkit.pipeline
import calkit.provenance
from app.api.deps import CurrentUser, SessionDep
from app.api.routes.projects.core import (
    STAGE_NAME_RE,
    _dump_ck_stage_map,
    _inside,
    _validate_ck_stage,
)
from app.api.routes.projects.figures import _clean_rel_path
from app.config import settings
from app.core import logger, ryaml
from app.dvc import run_dvc_command
from app.git import (
    get_ck_info_from_repo,
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


MAX_SOURCE_BYTES = 500_000_000
# A source bigger than this is stored with DVC rather than in Git
SOURCE_GIT_MAX_BYTES = 1_000_000


class StageExportPost(BaseModel):
    # What the document shows, e.g., a figure a paper includes
    path: str
    # The file it's exported from, in the project or uploaded there
    source_path: str
    # An uploaded source, base64-encoded
    content: str | None = None
    # The app it's exported with, e.g., Photoshop, for a manual step's
    # message
    app: str | None = None
    # A manual step even when an app could export it, e.g., an SVG someone
    # exports from Illustrator
    manual_step: bool = False


class StageExport(BaseModel):
    stage_name: str
    stage_yaml: str
    # The app's export kind, e.g., inkscape-export, when it exports as the
    # pipeline runs, or manual-step, when a person does
    kind: str
    message: str


@router.post("/projects/{owner_name}/{project_name}/pipeline/stages/export")
def post_project_stage_export(
    owner_name: str,
    project_name: str,
    req: StageExportPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> StageExport:
    """Record that a figure is exported from a file someone made, e.g., a
    PNG from an Inkscape SVG or a Photoshop file.

    An app that can export it, e.g., Inkscape, does so as the pipeline
    runs. Otherwise it's a manual step, which asks someone to export it
    again whenever the source changes. Either way the source, uploaded or
    already in the project, is recorded as created by the current user.
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
    path = _clean_rel_path(req.path, "path")
    source_path = _clean_rel_path(req.source_path, "source")
    if source_path == path:
        raise HTTPException(422, "A file can't be exported from itself")
    if not calkit.provenance.can_be_created_by_person(source_path):
        raise HTTPException(
            422,
            f"'{source_path}' is exported from something itself; pick the "
            "file it's made from, e.g., a Photoshop file",
        )
    full_source = os.path.join(wdir, source_path)
    content = None
    if req.content is not None:
        try:
            content = base64.b64decode(req.content, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "Source content isn't valid base64")
        if len(content) > MAX_SOURCE_BYTES:
            raise HTTPException(413, "Source is too large")
        # An upload never replaces a different file already there
        if os.path.isfile(full_source):
            with open(full_source, "rb") as fb:
                if fb.read() != content:
                    raise HTTPException(
                        409,
                        f"'{source_path}' is already in the project; pick "
                        "it without uploading, or upload under another name",
                    )
    elif not (
        os.path.isfile(full_source) or os.path.isfile(full_source + ".dvc")
    ):
        raise HTTPException(404, f"'{source_path}' is not in the project")
    ck_info = get_ck_info_from_repo(repo=repo)
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    producer = calkit.pipeline.get_stage_for_output(path, ck_info)
    if producer is not None:
        raise HTTPException(409, f"'{path}' is made by stage '{producer}'")
    # The app that exports the source as the pipeline runs, if any can
    exporter = None
    kind = "manual-step"
    for app_kind, app_label, module in [
        ("inkscape-export", "Inkscape", calkit.inkscape),
        ("gimp-export", "GIMP", calkit.gimp),
    ]:
        try:
            module.check_export(source_path, path)
        except ValueError:
            # e.g., a JPEG from an SVG, which Inkscape doesn't write
            continue
        if not req.manual_step:
            exporter, kind = app_label, app_kind
    app_name = (req.app or "").strip()
    message = (
        f"Exported from {source_path} with {exporter}"
        if exporter is not None
        else f"In {app_name}, export {path} from {source_path}"
        if app_name
        else f"Export {path} from {source_path}"
    )
    stem = os.path.splitext(os.path.basename(path))[0]
    slug = "-".join(
        "".join(c if c.isalnum() else " " for c in stem.lower()).split()
    )
    base_name = f"export-{slug or 'figure'}"
    stage_name = base_name
    n = 2
    while stage_name in stages:
        stage_name = f"{base_name}-{n}"
        n += 1
    tracked = bool(repo.git.ls_files("--", path).strip())
    output: str | dict[str, str] = (
        {"path": path, "storage": "git"} if tracked else path
    )
    stage: dict[str, Any] = (
        {"kind": kind, "source_path": source_path, "outputs": [output]}
        if exporter is not None
        else {
            "kind": "manual-step",
            "message": message,
            # The step opens the source in the app it's exported with
            **(
                {"open": {"app": app_name, "path": source_path}}
                if app_name
                else {}
            ),
            "inputs": [source_path],
            "outputs": [output],
        }
    )
    _validate_ck_stage(stage, stage_name)
    # The source is the person's, unless something already says otherwise
    person = {"email": current_user.email}
    if current_user.full_name:
        person["name"] = current_user.full_name
    entry = next(
        (
            e
            for items in ck_info.values()
            if isinstance(items, list)
            for e in items
            if isinstance(e, dict) and e.get("path") == source_path
        ),
        None,
    )
    if entry is None:
        ck_info.setdefault("misc", []).append(
            {"path": source_path, "created_by": [person]}
        )
    elif not (
        entry.get("created_by")
        or entry.get("imported_from")
        or entry.get("stage")
    ):
        entry["created_by"] = [person]
    if content is not None:
        os.makedirs(os.path.dirname(full_source) or wdir, exist_ok=True)
        with open(full_source, "wb") as fb:
            fb.write(content)
        if len(content) > SOURCE_GIT_MAX_BYTES:
            if not os.path.isdir(os.path.join(wdir, ".dvc")):
                run_dvc_command(["init"], wdir=wdir, check=True)
            run_dvc_command(["add", source_path], wdir=wdir, check=True)
            # Put where the hub's DVC remote serves it, by its hash
            with open(full_source + ".dvc") as f:
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
        f"Export {path} from {source_path}"
        + (f" with {exporter}" if exporter is not None else " manually"),
    )
    return StageExport(
        stage_name=stage_name,
        stage_yaml=_dump_ck_stage_map(stage),
        kind=stage["kind"],
        message=message,
    )
