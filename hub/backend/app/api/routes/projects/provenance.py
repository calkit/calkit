"""Where an artifact, or one value in a results file, came from.

The answer a PDF link, the results page, and the browser extension's card
all show: the value, the stage that produces it, what to open to change it,
what it reads, and whether it's out of date.
"""

import hashlib
import json
import posixpath
from urllib.parse import quote

from fastapi import APIRouter, HTTPException

import app.projects
import calkit.core
import calkit.provenance
from app.api.deps import CurrentUserOptional, SessionDep
from app.api.routes.projects.core import (
    DEFAULT_REPO_TTL,
    LATEX_COMPONENT_VALUES_MAX_BYTES,
)
from app.api.routes.projects.figures import _clean_rel_path
from app.config import settings
from app.core import logger
from app.git import get_repo, get_repo_tree_for_ref
from app.models import Provenance
from app.pipeline import pipeline_at_ref

router = APIRouter()

# Where what each import last brought in is recorded
IMPORT_LOCK_PATH = calkit.provenance.IMPORT_LOCK_FPATH.replace("\\", "/")


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
        repo,
        ref,
        project.owner_account_name,
        project.name,
        storages=app.projects.get_storages_for_project(project),
    )
    out = Provenance.model_validate(
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
    # What the hub adds for an import from another project or a Git repo:
    # a link to the source on the hub, and whether it can be updated, and
    # has been since, which only the hub can read the other project to tell
    traced = out.copied_from or path
    entry_path = out.origin_path or traced
    found = calkit.provenance.find_artifact(ck_info, entry_path)
    imported = (
        calkit.provenance.get_import_info(found[1].get("imported_from"))
        if found
        else None
    )
    if imported is None:
        return out
    src_project = imported.get("project")
    src_path = imported.get("path")
    if src_project and not out.origin_url:
        out.origin_url = (
            f"{settings.frontend_host.rstrip('/')}/"
            f"{str(src_project).strip('/')}/files"
            + (f"?path={quote(str(src_path))}" if src_path else "")
        )
    # Only for the import itself, not a copy a stage makes of it, since
    # updating that would need the copy regenerated too
    out.updatable = entry_path == traced == path and bool(
        src_project or imported.get("git_repo_url")
    )
    # Newer when the source's file isn't what was last brought in. Telling
    # for a Git repo would mean cloning it, so that's left to updating.
    if out.updatable and src_project and src_path:
        try:
            locks = (
                json.loads(tree.read_text(IMPORT_LOCK_PATH))
                if tree.is_file(IMPORT_LOCK_PATH)
                else {}
            )
            recorded = (locks.get(traced) or {}).get("hash")
            src_owner, src_name = str(src_project).strip("/").split("/", 1)
            src_repo_project = app.projects.get_project(
                session=session,
                owner_name=src_owner,
                project_name=src_name,
                current_user=current_user,
                min_access_level="read",
            )
            src_repo = get_repo(
                project=src_repo_project,
                user=current_user,
                session=session,
                ttl=DEFAULT_REPO_TTL,
                read_only=True,
            )
            src_tree = get_repo_tree_for_ref(src_repo, None)
            if isinstance(recorded, str):
                # From Git or DVC storage, as importing reads it
                data = app.projects.read_project_file(
                    project=src_repo_project,
                    tree=src_tree,
                    path=posixpath.normpath(str(src_path)),
                    max_bytes=calkit.core.DVC_SIZE_THRESH_BYTES - 1,
                    session=session,
                    current_user=current_user,
                )
                digest = hashlib.sha256(data).hexdigest()
                out.update_available = recorded != (
                    f"{calkit.provenance.HASH_ALGORITHM}:{digest}"
                )
        except Exception as e:
            logger.info(f"Can't check {src_project} for updates: {e}")
    return out
