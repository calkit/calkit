"""Where an artifact, or one value in a results file, came from.

The answer a PDF link, the results page, and the browser extension's card
all show: the value, the stage that produces it, what to open to change it,
what it reads, and whether it's out of date.
"""

import base64
import json
import posixpath
from typing import Any

from fastapi import APIRouter

import app.projects
import calkit.pipeline
import calkit.questions
from app.api.deps import CurrentUserOptional, SessionDep
from app.api.routes.projects.core import DEFAULT_REPO_TTL
from app.api.routes.projects.figures import _clean_rel_path
from app.core import logger, ryaml
from app.git import get_repo, get_repo_tree_for_ref
from app.models import Provenance, StageStatus
from app.pipeline import find_stage_for_path, pipeline_at_ref

router = APIRouter()

# A value bigger than this, e.g., a whole table exported as a key, is
# described rather than sent
MAX_VALUE_BYTES = 100_000
RESULTS_EXTS = (".json", ".yaml", ".yml", ".toml")
# The stage fields that name what someone edits to change its output
SOURCE_FIELDS = ("script_path", "notebook_path", "target_path")


def _read_value(
    project: Any, repo: Any, ref: str | None, path: str, key: str | None
) -> tuple[Any, str | None]:
    """The value at ``key`` in a results file, or the whole file without
    one, or why it can't be read.
    """
    try:
        item = app.projects.get_contents_from_repo(
            project=project, repo=repo, path=path, ref=ref
        )
    except Exception as e:
        logger.info(f"Can't read {path} at {ref}: {e}")
        return None, f"{path} can't be read"
    if item.content is None:
        return None, f"{path} has no content to read"
    text = base64.b64decode(item.content).decode("utf-8", "replace")
    lower = path.lower()
    try:
        if lower.endswith(".json"):
            data = json.loads(text)
        elif lower.endswith((".yaml", ".yml")):
            data = ryaml.load(text)
        elif lower.endswith(".toml"):
            import tomllib

            data = tomllib.loads(text)
        else:
            return None, f"{path} isn't JSON, YAML, or TOML"
        value = (
            data if key is None else calkit.questions.resolve_key(data, key)
        )
    except KeyError:
        return None, f"{key} isn't in {path}"
    except Exception as e:
        return None, f"{path} can't be parsed: {e}"
    # Plain JSON, since YAML loads into its own mapping types
    encoded = json.dumps(value, default=str)
    if len(encoded) > MAX_VALUE_BYTES:
        return None, f"{key or path} is too big to show"
    return json.loads(encoded), None


@router.get("/projects/{owner_name}/{project_name}/provenance")
def get_project_provenance(
    owner_name: str,
    project_name: str,
    path: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    key: str | None = None,
    ref: str | None = None,
) -> Provenance:
    def stage_for(path: str) -> str | None:
        # A declaration knows better than a path match, which knows better
        # than the pipeline's outputs as written, which cover stages never
        # run
        declared = next(
            (
                artifact["stage"]
                for kind in ("results", "figures", "tables", "datasets")
                for artifact in ck_info.get(kind) or []
                if isinstance(artifact, dict)
                and artifact.get("path") == path
                and artifact.get("stage")
            ),
            None,
        )
        return (
            declared
            or find_stage_for_path(
                path, pipeline.dvc_lock, valid_stages=set(pipeline.statuses)
            )
            or calkit.pipeline.get_stage_for_output(path, ck_info)
        )

    def ck_stage_for(stage: str) -> dict[str, Any] | None:
        # A matrix stage's expansions share one definition
        stages = (ck_info.get("pipeline") or {}).get("stages") or {}
        ck_stage = stages.get(stage.split("@")[0])
        return ck_stage if isinstance(ck_stage, dict) else None

    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
        read_only=True,
    )
    path = _clean_rel_path(path, "path")
    ck_info = app.projects.get_ck_info_for_ref(
        project=project, repo=repo, ref=ref
    )
    tree = get_repo_tree_for_ref(repo, ref)
    pipeline = pipeline_at_ref(
        repo, ref, project.owner_account_name, project.name
    )
    lock_outs = {
        out.get("path")
        for stage in (pipeline.dvc_lock.get("stages") or {}).values()
        for out in (stage or {}).get("outs") or []
    }
    out = Provenance(
        path=path,
        key=key,
        exists=(
            tree.is_file(path)
            or tree.is_dir(path)
            or tree.is_file(path + ".dvc")
            or path in lock_outs
        ),
    )
    if out.exists and (key is not None or path.lower().endswith(RESULTS_EXTS)):
        out.value, out.value_error = _read_value(project, repo, ref, path, key)
    stage = stage_for(path)
    # A copy, e.g., a figure a map-paths stage put in the paper's folder, is
    # described by what made the original, and is stale if the copy is
    traced = path
    copy_stale = False
    for _ in range(10):
        ck_stage = ck_stage_for(stage) if stage else None
        src = (
            calkit.pipeline.get_map_paths_source(ck_stage, traced)
            if ck_stage is not None
            else None
        )
        if stage is None or src is None:
            break
        copy_status = pipeline.statuses.get(stage)
        copy_stale |= copy_status is not None and copy_status.status == "stale"
        out.copy_stage = out.copy_stage or stage
        traced = src
        stage = stage_for(src)
    if traced != path:
        out.copied_from = traced
    if copy_stale:
        out.stale_reason = "pipeline"
    if stage is None:
        return out
    out.stage = stage
    status = pipeline.statuses.get(stage)
    if status is not None:
        out.stage_status = StageStatus.model_validate(status.model_dump())
        if status.status == "stale":
            out.stale_reason = "pipeline"
        elif stage in pipeline.frozen and out.stale_reason is None:
            out.stale_reason = "frozen"
    base = stage.split("@")[0]
    ck_stage = ck_stage_for(stage)
    source = None
    if ck_stage is not None:
        out.stage_kind = ck_stage.get("kind")
        wdir = ck_stage.get("wdir") or ""
        field = next((f for f in SOURCE_FIELDS if ck_stage.get(f)), None)
        if field is not None:
            source = posixpath.normpath(posixpath.join(wdir, ck_stage[field]))
            out.source = source
        elif isinstance(ck_stage.get("command"), str):
            out.command = ck_stage["command"]
    # What DVC tracks it reading, from the run if there was one
    lock_stage = (pipeline.dvc_lock.get("stages") or {}).get(stage) or {}
    yaml_stage = (pipeline.dvc_yaml.get("stages") or {}).get(base) or {}
    dvc_wdir = yaml_stage.get("wdir") or ""
    deps = [
        dep.get("path") if isinstance(dep, dict) else dep
        for dep in lock_stage.get("deps") or yaml_stage.get("deps") or []
    ]
    for dep in deps:
        if not isinstance(dep, str):
            continue
        dep = posixpath.normpath(posixpath.join(dvc_wdir, dep))
        # Calkit's own bookkeeping, e.g., environment locks, and the source
        # shown on its own
        if dep.startswith(".calkit/") or dep in (source, "calkit.yaml"):
            continue
        out.inputs.append(dep)
    return out
