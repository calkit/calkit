"""Copying project files into a publication, as a pipeline stage.

A paper usually wants figures that live elsewhere in the project (the
root ``figures`` directory, say) under its own directory, where LaTeX can
find them without ``../``. Copying by hand would drift; a map-paths stage
makes the copy part of the pipeline, so the paper always builds from the
figures as they are.
"""

import os
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import app.projects
import calkit.pipeline
from app.api.deps import CurrentUser, SessionDep
from app.api.routes.projects.core import (
    STAGE_NAME_RE,
    _dump_ck_stage_map,
    _validate_ck_stage,
)
from app.api.routes.projects.figures import _clean_rel_path
from app.core import ryaml
from app.git import (
    get_ck_info_from_repo,
    get_repo,
    get_repo_tree_for_ref,
    record_project_update,
)
from app.models import PipelineStage

router = APIRouter()

MapKind = Literal[
    "file-to-file", "file-to-dir", "dir-to-dir-merge", "dir-to-dir-replace"
]


class MapPathEntry(BaseModel):
    src: str
    dest: str
    # Worked out from what ``src`` is when not given
    kind: MapKind | None = None


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
        kind = entry.kind or (
            "dir-to-dir-merge"
            if is_dir
            else (
                "file-to-dir" if entry.dest.endswith("/") else "file-to-file"
            )
        )
        if is_dir != kind.startswith("dir"):
            what = "a directory" if is_dir else "a file"
            raise HTTPException(
                422, f"'{src}' is {what}, so it can't be {kind}"
            )
        if any(
            p.get("src") == src and p.get("dest") == dest for p in existing
        ):
            continue
        existing.append({"kind": kind, "src": src, "dest": dest})
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
    with open(os.path.join(wdir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
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
            with open(dvc_path, "w") as f:
                ryaml.dump(dvc_yaml, f)
        repo.git.add("-A")
    except Exception as e:
        repo.git.checkout("--", ".")
        repo.git.clean("-fd")
        raise HTTPException(422, f"Could not compile the pipeline: {e}")
    if repo.is_dirty():
        repo.git.commit(["-m", message])
        repo.git.push(["origin", repo.active_branch.name])
        record_project_update(project, repo, session)
