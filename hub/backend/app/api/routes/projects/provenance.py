"""Where an artifact, or one value in a results file, came from.

The answer a PDF link, the results page, and the browser extension's card
all show: the value, the stage that produces it, what to open to change it,
what it reads, and whether it's out of date.
"""

from fastapi import APIRouter, HTTPException

import app.projects
import calkit.provenance
from app.api.deps import CurrentUserOptional, SessionDep
from app.api.routes.projects.core import (
    DEFAULT_REPO_TTL,
    LATEX_COMPONENT_VALUES_MAX_BYTES,
)
from app.api.routes.projects.figures import _clean_rel_path
from app.core import logger
from app.git import get_repo, get_repo_tree_for_ref
from app.models import Provenance
from app.pipeline import pipeline_at_ref

router = APIRouter()


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
    def read_bytes(path: str) -> bytes:
        try:
            return app.projects.read_project_file(
                project=project,
                tree=tree,
                path=path,
                max_bytes=LATEX_COMPONENT_VALUES_MAX_BYTES,
                session=session,
                current_user=current_user,
            )
        except HTTPException as e:
            raise ValueError(str(e.detail))
        except Exception as e:
            logger.info(f"Can't read {path}: {e}")
            raise

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
    return Provenance.model_validate(
        calkit.provenance.get_path_provenance(
            path,
            key=key,
            ck_info=ck_info,
            dvc_yaml=pipeline.dvc_yaml,
            dvc_lock=pipeline.dvc_lock,
            stage_statuses={
                name: status.model_dump()
                for name, status in pipeline.statuses.items()
            },
            frozen=set(pipeline.frozen),
            is_file=tree.is_file,
            is_dir=tree.is_dir,
            listdir=tree.listdir,
            read_bytes=read_bytes,
            is_dvc_output=lambda p: (
                p
                in app.projects.dvc_outputs_from_tree(
                    project=project, tree=tree
                )
            ),
        )
    )
