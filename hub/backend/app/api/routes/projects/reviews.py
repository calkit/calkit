"""Reviewed Word documents, and merging them into the LaTeX source.

The lead exports a manuscript to Word with ``calkit latex to-docx``, and
reviewers mark it up in Word. This is where the marked-up copies come
back to: a reviewer uploads one, it goes into the project repo under
``reviews/`` as a DVC-tracked file, and the lead works through what it
proposes -- accepting, rejecting, or leaving each tracked change and
comment thread -- and merges the decisions into the ``.tex`` source as a
commit. The CLI's ``merge-docx`` reads the same documents and writes the
same records, so a review handled here can be finished on a laptop and
vice versa.
"""

import hashlib
import logging
import os
import posixpath
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

import app.projects
import calkit.docx
import calkit.latex
import calkit.review
from app.api.deps import CurrentUser, SessionDep
from app.config import settings
from app.dvc import get_data_fpath_for_md5, run_dvc_command
from app.git import get_repo, record_project_update
from app.models import Project
from app.storage import (
    get_object_fs,
    make_data_fpath,
    remove_gcs_content_type,
)
from calkit.models.docx import (
    LatexDocxComment,
    LatexDocxEdit,
    LatexDocxMerge,
)

logger = logging.getLogger(__name__)

router = APIRouter()

REVIEWS_DIR = "reviews"
MAX_REVIEW_BYTES = 50_000_000


class LatexReview(BaseModel):
    """A reviewed Word document in the project, and where it stands."""

    path: str
    export_id: str
    source: str = Field(description="Main .tex file it was exported from.")
    rev: str | None = Field(description="Commit it was exported at.")
    size: int
    storage: str = Field(description="'git' or 'dvc'.")
    last_modified_by: str | None
    authors: list[str]
    # What's left to decide: edits not yet applied or rejected, and
    # comment threads not yet in the source or dismissed
    open_edits: int
    open_comments: int
    unplaced: int
    media_changed: list[str] = []
    last_merged: datetime | None = None


class LatexReviewPlan(LatexReview):
    edits: list[LatexDocxEdit]
    comments: list[LatexDocxComment]


class LatexReviewMergePost(BaseModel):
    accept: list[str] = Field(default=[], description="Edit keys to apply.")
    reject: list[str] = Field(
        default=[], description="Edit keys to decline for good."
    )
    dismiss: list[str] = Field(
        default=[], description="Comment thread keys to keep out."
    )
    write_comments: bool = True
    message: str | None = None


class LatexReviewMergeResult(BaseModel):
    record: LatexDocxMerge
    commit: str | None = Field(
        description="The commit made, or None when nothing changed."
    )
    review: LatexReview


def _safe_review_path(path: str) -> str:
    path = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    if (
        not path
        or path.startswith("..")
        or "/../" in path
        or not path.lower().endswith(".docx")
    ):
        raise HTTPException(400, "Path must be a .docx inside the project")
    return path


def _review_paths(wdir: str) -> list[str]:
    """Every .docx under reviews/, whether Git- or DVC-tracked."""
    root = os.path.join(wdir, REVIEWS_DIR)
    if not os.path.isdir(root):
        return []
    found: set[str] = set()
    for dirpath, _, names in os.walk(root):
        rel_dir = os.path.relpath(dirpath, wdir).replace(os.sep, "/")
        for name in names:
            if name.lower().endswith(".docx"):
                found.add(f"{rel_dir}/{name}")
            elif name.lower().endswith(".docx.dvc"):
                found.add(f"{rel_dir}/{name[: -len('.dvc')]}")
    return sorted(found)


def _pointer(wdir: str, path: str) -> dict | None:
    pointer = os.path.join(wdir, path + ".dvc")
    if not os.path.isfile(pointer):
        return None
    with open(pointer) as f:
        data = yaml.safe_load(f) or {}
    outs = data.get("outs") or [{}]
    return outs[0] if isinstance(outs[0], dict) else None


def _md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _materialize(project: Project, wdir: str, path: str) -> str:
    """Make sure the document's bytes are in the working tree.

    A DVC-tracked file isn't checked out with the repo; its bytes are
    fetched from the project's storage when they aren't already there.
    """
    full = os.path.join(wdir, path)
    out = _pointer(wdir, path)
    if out is None:
        if not os.path.isfile(full):
            raise HTTPException(404, f"{path} is not in the project")
        return "git"
    md5 = str(out.get("md5") or "")
    if os.path.isfile(full) and _md5(full) == md5:
        return "dvc"
    fs = get_object_fs()
    fpath = get_data_fpath_for_md5(
        owner_name=project.owner_account_name,
        project_name=project.name,
        md5=md5,
        fs=fs,
    )
    if fpath is None:
        raise HTTPException(404, f"{path} has not been pushed to storage")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with fs.open(fpath, "rb") as src, open(full, "wb") as dst:
        dst.write(src.read())
    return "dvc"


def _store(project: Project, md5: str, data: bytes) -> None:
    fs = get_object_fs()
    fpath = make_data_fpath(
        owner_name=project.owner_account_name,
        project_name=project.name,
        idx=md5[:2],
        md5=md5[2:],
    )
    with fs.open(fpath, "wb") as f:
        f.write(data)  # type: ignore[arg-type]
    if settings.ENVIRONMENT != "local":
        remove_gcs_content_type(fpath)


def _last_merged(wdir: str, export_id: str, docx: str) -> datetime | None:
    merges_dir = os.path.join(wdir, calkit.latex.DOCX_MERGES_DIR)
    if not os.path.isdir(merges_dir):
        return None
    latest: datetime | None = None
    for name in os.listdir(merges_dir):
        if not name.startswith(export_id + "-"):
            continue
        try:
            record = LatexDocxMerge.model_validate_json(
                Path(merges_dir, name).read_text(encoding="utf-8")
            )
        except Exception:
            continue
        if record.docx == docx and (latest is None or record.created > latest):
            latest = record.created
    return latest


def _plan(
    project: Project, wdir: str, path: str, storage: str
) -> tuple[calkit.review.MergePlan, LatexReview]:
    """Read the document against the source as it is at HEAD."""
    try:
        plan = calkit.review.plan(path, wdir=wdir)
    except (calkit.review.NotAnExportError, FileNotFoundError) as e:
        raise HTTPException(422, str(e))
    review = LatexReview(
        path=path,
        export_id=plan.export_id,
        source=plan.source,
        rev=plan.rev,
        size=os.path.getsize(os.path.join(wdir, path)),
        storage=storage,
        last_modified_by=plan.last_modified_by,
        authors=plan.authors,
        open_edits=sum(
            1 for e in plan.edits if e.status in ("applicable", "pending")
        ),
        open_comments=sum(
            1 for c in plan.comments if c.status in ("new", "updated")
        ),
        unplaced=sum(1 for e in plan.edits if e.status == "unplaced")
        + sum(1 for c in plan.comments if c.status == "unplaced"),
        media_changed=plan.media_changed,
        last_merged=_last_merged(wdir, plan.export_id, path),
    )
    return plan, review


@router.get("/projects/{owner_name}/{project_name}/latex-reviews")
def get_project_latex_reviews(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
    source: str | None = None,
) -> list[LatexReview]:
    """Reviewed documents in the project, optionally for one .tex source.

    Documents that can't be read as Calkit exports, or whose source is
    gone, are left out rather than failing the whole list.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    wdir = str(repo.working_dir)
    out: list[LatexReview] = []
    for path in _review_paths(wdir):
        try:
            storage = _materialize(project, wdir, path)
            _, review = _plan(project, wdir, path, storage)
        except HTTPException as e:
            logger.warning(f"Skipping review {path}: {e.detail}")
            continue
        if source is None or review.source == source:
            out.append(review)
    return out


@router.post("/projects/{owner_name}/{project_name}/latex-reviews")
def post_project_latex_review(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
    path: Annotated[str | None, Form()] = None,
    message: Annotated[str | None, Form()] = None,
) -> LatexReviewPlan:
    """Add a reviewed document to the project.

    It lands under ``reviews/`` tracked by DVC, so the repo records that
    the review happened without carrying the binary, and comes back with
    what merging it would do.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    data = file.file.read(MAX_REVIEW_BYTES + 1)
    if len(data) > MAX_REVIEW_BYTES:
        raise HTTPException(413, "Document is too large")
    if not data:
        raise HTTPException(400, "Document is empty")
    if path is None:
        name = re.sub(r"[^\w.\-]+", "-", os.path.basename(file.filename or ""))
        path = f"{REVIEWS_DIR}/{name or 'review.docx'}"
    path = _safe_review_path(path)
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    wdir = str(repo.working_dir)
    full = os.path.join(wdir, path)
    # Refuse anything that can't be merged before it touches the repo
    with tempfile.NamedTemporaryFile(suffix=".docx") as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            original = calkit.docx.Document(tmp.name).read_original()
        except Exception:
            original = None
    if original is None:
        raise HTTPException(
            422,
            "This document wasn't exported by Calkit, or its metadata was "
            "stripped by another application",
        )
    if not os.path.isfile(os.path.join(wdir, original.source)):
        raise HTTPException(
            422, f"Its source {original.source} is not in the project"
        )
    os.makedirs(os.path.dirname(full), exist_ok=True)
    existed = os.path.isfile(full) or os.path.isfile(full + ".dvc")
    with open(full, "wb") as f:
        f.write(data)
    if not os.path.isdir(os.path.join(wdir, ".dvc")):
        run_dvc_command(["init"], wdir=wdir, check=True)
    run_dvc_command(["add", path], wdir=wdir, check=True)
    to_stage = [path + ".dvc"]
    gitignore = posixpath.join(posixpath.dirname(path), ".gitignore")
    if os.path.isfile(os.path.join(wdir, gitignore)):
        to_stage.append(gitignore)
    repo.git.add(to_stage)
    out = _pointer(wdir, path) or {}
    md5 = str(out.get("md5") or _md5(full))
    _store(project, md5, data)
    if repo.git.diff(["--staged", "--name-only"]):
        repo.git.commit(
            ["-m", message or f"{'Update' if existed else 'Add'} {path}"]
        )
        repo.git.push(["origin", repo.active_branch.name])
        record_project_update(project, repo, session)
    plan, review = _plan(project, wdir, path, "dvc")
    return LatexReviewPlan(
        **review.model_dump(), edits=plan.edits, comments=plan.comments
    )


@router.get("/projects/{owner_name}/{project_name}/latex-reviews/{path:path}")
def get_project_latex_review(
    owner_name: str,
    project_name: str,
    path: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> LatexReviewPlan:
    """What merging a reviewed document would do to the source now."""
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    path = _safe_review_path(path)
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    wdir = str(repo.working_dir)
    storage = _materialize(project, wdir, path)
    plan, review = _plan(project, wdir, path, storage)
    return LatexReviewPlan(
        **review.model_dump(), edits=plan.edits, comments=plan.comments
    )


@router.post(
    "/projects/{owner_name}/{project_name}/latex-reviews/{path:path}/merge"
)
def post_project_latex_review_merge(
    owner_name: str,
    project_name: str,
    path: str,
    req: LatexReviewMergePost,
    session: SessionDep,
    current_user: CurrentUser,
) -> LatexReviewMergeResult:
    """Write the lead's decisions into the source and commit them.

    Only what's named is decided; anything else stays open for a later
    pass, here or with the CLI. Rejected and dismissed items are recorded
    in the merge record so they aren't offered again.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    path = _safe_review_path(path)
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    wdir = str(repo.working_dir)
    storage = _materialize(project, wdir, path)
    plan, _ = _plan(project, wdir, path, storage)
    known = {e.key for e in plan.edits} | {c.key for c in plan.comments}
    unknown = (set(req.accept) | set(req.reject) | set(req.dismiss)) - known
    if unknown:
        raise HTTPException(
            422, "Unknown items: " + ", ".join(sorted(unknown))
        )
    record = calkit.review.apply(
        plan,
        accept=set(req.accept),
        reject=set(req.reject),
        dismiss=set(req.dismiss),
        write_comments=req.write_comments,
    )
    # Only what this pass changed counts: source that was written, or a
    # new rejection or dismissal. Items decided earlier keep their status
    # in every later record.
    before = {e.key: e.status for e in plan.edits}
    before |= {c.key: c.status for c in plan.comments}
    decided = bool(repo.git.diff(["--name-only"] + plan.paths)) or any(
        c.status in ("rejected", "dismissed") and before.get(c.key) != c.status
        for c in [*record.changes, *record.comments]
    )
    commit = None
    if decided:
        # A pass that decided nothing leaves no record, so the history is
        # of decisions rather than of page loads
        record_path = calkit.review.write_record(record, wdir=wdir)
        repo.git.add([record_path] + plan.paths)
    if decided and repo.git.diff(["--staged", "--name-only"]):
        applied = sum(1 for c in record.changes if c.status == "applied")
        comments = record.comments_added + record.comments_updated
        parts = []
        if applied:
            parts.append(f"{applied} edit{'s' if applied != 1 else ''}")
        if comments:
            parts.append(f"{comments} comment{'s' if comments != 1 else ''}")
        what = " and ".join(parts) or "decisions"
        repo.git.commit(["-m", req.message or f"Merge {what} from {path}"])
        repo.git.push(["origin", repo.active_branch.name])
        record_project_update(project, repo, session)
        commit = repo.head.commit.hexsha
    _, review = _plan(project, wdir, path, storage)
    return LatexReviewMergeResult(record=record, commit=commit, review=review)
