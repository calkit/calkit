"""Contribution requests: asking someone for a review by link.

A project lead creates a request against a publication, optionally
attaching the Word copy exported with ``calkit latex to-docx``. The
recipient gets a link carrying a token, opens a page that needs no
account, downloads the document, and uploads it back marked up. The
returned copy lands in the repo under ``reviews/`` like any other, so the
lead triages it on the publication page or with ``merge-docx``.

The request itself is recorded in the repo, one YAML file per request
under ``.calkit/requests``, alongside the responses it received. The
database row here holds what only delivery needs: the token's hash,
whether the email went out, how many times the link was opened.
"""

import hashlib
import logging
import os
import re
import secrets
import uuid
from datetime import timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlmodel import select

import app.projects
import calkit.contrib
from app import messaging, utcnow
from app.api.deps import CurrentUser, CurrentUserOptional, SessionDep
from app.api.routes.projects.reviews import (
    commit_staged,
    default_review_path,
    read_upload,
    stage_review,
)
from app.config import settings
from app.git import get_repo, get_repo_tree_for_ref
from app.models import Project, User
from app.models.contrib import (
    ContribAttachment,
    ContribAttachmentPublic,
    ContribRequest,
    ContribRequestCreated,
    ContribRequestPatch,
    ContribRequestPost,
    ContribRequestPublic,
    ContribRequestResponse,
    ContribRequestView,
    ContribResponsePublic,
)
from calkit.models.contrib import (
    ContribRequestRecipient,
    ContribRequestRecord,
    ContribRequestTarget,
    ContribResponseRecord,
)

logger = logging.getLogger(__name__)

router = APIRouter()

SECRET_TOKEN_BYTES = 32
MAX_DOCUMENT_BYTES = 50_000_000


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _link(raw_token: str) -> str:
    return f"{settings.frontend_host.rstrip('/')}/review/{quote(raw_token)}"


def _response_public(resp: ContribRequestResponse) -> ContribResponsePublic:
    return ContribResponsePublic(
        id=resp.id,
        request_id=resp.request_id,
        responder_name=resp.responder_name,
        responder_email=resp.responder_email,
        email_verified=resp.email_verified,
        status=resp.status,
        via=resp.via,
        external_thread_url=resp.external_thread_url,
        decline_reason=resp.decline_reason,
        recommendation=resp.recommendation,
        message=resp.message,
        git_rev=resp.git_rev,
        branch_name=resp.branch_name,
        github_pr_url=resp.github_pr_url,
        submitted_at=resp.submitted_at,
        reviewed_at=resp.reviewed_at,
        review_note=resp.review_note,
        task_count=resp.task_count,
        accepted_count=resp.accepted_count,
        created=resp.created,
        attachments=[
            ContribAttachmentPublic(
                id=a.id,
                filename=a.filename,
                content_type=a.content_type,
                size_bytes=a.size_bytes,
                created=a.created,
            )
            for a in resp.attachments
        ],
    )


def _public(req: ContribRequest) -> ContribRequestPublic:
    return ContribRequestPublic(
        id=req.id,
        title=req.title,
        message=req.message,
        direction=req.direction,
        in_response_to_request_id=req.in_response_to_request_id,
        target_kind=req.target_kind,
        target_path=req.target_path,
        document_path=req.document_path,
        git_ref=req.git_ref,
        git_rev=req.git_rev,
        permission=req.permission,
        identity_requirement=req.identity_requirement,
        due_at=req.due_at,
        round=req.round,
        supersedes_request_id=req.supersedes_request_id,
        email=req.email,
        contributor_name=req.contributor_name,
        approval_status=req.approval_status,
        approved_at=req.approved_at,
        denial_reason=req.denial_reason,
        public=req.public,
        expires_at=req.expires_at,
        max_responses=req.max_responses,
        response_count=req.response_count,
        closed_at=req.closed_at,
        revoked=req.revoked,
        github_issue_url=req.github_issue_url,
        view_count=req.view_count,
        created=req.created,
        responses=[
            _response_public(r)
            for r in sorted(req.responses, key=lambda r: r.created)
            if r.status != "draft"
        ],
    )


def _record(
    req: ContribRequest, created_by: User | None
) -> ContribRequestRecord:
    """The repo's copy of a request: everything the lead decided."""
    to = None
    if req.email or req.contributor_name:
        to = ContribRequestRecipient(
            name=req.contributor_name, email=req.email
        )
    status = (
        "revoked" if req.revoked else "closed" if req.closed_at else "open"
    )
    return ContribRequestRecord(
        id=str(req.id),
        title=req.title,
        message=req.message,
        target=ContribRequestTarget(
            kind=req.target_kind,  # type: ignore[arg-type]
            path=req.target_path,
        ),
        document=req.document_path,
        permission=req.permission,  # type: ignore[arg-type]
        identity=req.identity_requirement,  # type: ignore[arg-type]
        to=to,
        public=req.public,
        created=req.created,
        created_by=created_by.email if created_by else None,
        rev=req.git_rev,
        due=req.due_at,
        expires=req.expires_at,
        status=status,
    )


def _send_email(
    project: Project, req: ContribRequest, raw_token: str, sender: User
) -> bool:
    if not req.email or not settings.emails_enabled:
        return False
    email_data = messaging.generate_contrib_request_email(
        email_to=req.email,
        project_name=project.title or project.name,
        title=req.title,
        link=_link(raw_token),
        inviter=sender.full_name or sender.email,
        permission=req.permission,
        note=req.message,
        due=req.due_at.strftime("%B %-d") if req.due_at else None,
    )
    try:
        messaging.send_email(
            email_to=req.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
        return True
    except Exception:
        logger.exception("Failed to send contribution request email")
        return False


@router.post("/projects/{owner_name}/{project_name}/contrib-requests")
def post_project_contrib_request(
    owner_name: str,
    project_name: str,
    req_in: ContribRequestPost,
    session: SessionDep,
    current_user: CurrentUser,
) -> ContribRequestCreated:
    """Send a request for a review of a publication.

    Records it in the repo, mints the link, and emails it if there's a
    recipient and email is configured. The raw token comes back once.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    if req_in.direction != "outbound" or req_in.public:
        raise HTTPException(
            501, "Only outbound requests to a recipient are supported yet"
        )
    if req_in.target_kind != "publication" or not req_in.target_path:
        raise HTTPException(
            501, "Only requests targeting a publication are supported yet"
        )
    if req_in.permission not in ("view", "comment", "suggest"):
        raise HTTPException(
            400, "Permission must be 'view', 'comment', or 'suggest'"
        )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    wdir = str(repo.working_dir)
    tree = get_repo_tree_for_ref(repo, None)
    if req_in.document_path:
        doc = req_in.document_path.strip("/")
        if not (
            tree.is_file(doc)
            or os.path.isfile(os.path.join(wdir, doc + ".dvc"))
        ):
            raise HTTPException(
                422, f"Document {req_in.document_path} is not in the project"
            )
        if not doc.lower().endswith(".docx"):
            raise HTTPException(422, "The document must be a .docx")
        req_in.document_path = doc
    raw_token = secrets.token_urlsafe(SECRET_TOKEN_BYTES)
    expires_at = (
        utcnow() + timedelta(days=req_in.expires_days)
        if req_in.expires_days
        else None
    )
    req = ContribRequest(
        project_id=project.id,
        created_by_user_id=current_user.id,
        token_hash=_hash_token(raw_token),
        title=req_in.title.strip(),
        message=(req_in.message or "").strip() or None,
        direction="outbound",
        target_kind=req_in.target_kind,
        target_path=req_in.target_path,
        document_path=req_in.document_path,
        git_ref=repo.active_branch.name,
        git_rev=repo.head.commit.hexsha,
        permission=req_in.permission,
        identity_requirement=req_in.identity_requirement,
        due_at=req_in.due_at,
        email=(req_in.email or "").strip().lower() or None,
        contributor_name=(req_in.contributor_name or "").strip() or None,
        expires_at=expires_at,
        approval_status="approved",
        approved_by_user_id=current_user.id,
        approved_at=utcnow(),
        reply_key=secrets.token_urlsafe(16),
    )
    session.add(req)
    session.commit()
    session.refresh(req)
    # The repo is the record; the row is the index
    rel = calkit.contrib.save(_record(req, current_user), wdir=wdir)
    repo.git.add(rel)
    who = req.contributor_name or req.email or "a collaborator"
    commit_staged(
        project,
        repo,
        session,
        f"Request review of {req.target_path} from {who}",
    )
    email_sent = _send_email(project, req, raw_token, current_user)
    return ContribRequestCreated(
        **_public(req).model_dump(),
        token=raw_token,
        url=_link(raw_token),
        email_sent=email_sent,
    )


@router.get("/projects/{owner_name}/{project_name}/contrib-requests")
def get_project_contrib_requests(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
    target_path: str | None = None,
) -> list[ContribRequestPublic]:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    query = select(ContribRequest).where(
        ContribRequest.project_id == project.id
    )
    if target_path is not None:
        query = query.where(ContribRequest.target_path == target_path)
    reqs = session.exec(
        query.order_by(ContribRequest.created.desc())  # type: ignore[attr-defined]
    ).all()
    return [_public(r) for r in reqs]


@router.patch(
    "/projects/{owner_name}/{project_name}/contrib-requests/{request_id}"
)
def patch_project_contrib_request(
    owner_name: str,
    project_name: str,
    request_id: uuid.UUID,
    req_in: ContribRequestPatch,
    session: SessionDep,
    current_user: CurrentUser,
) -> ContribRequestPublic:
    """Close or revoke a request, or change its message or dates.

    The change is committed to the request's record in the repo too.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    req = session.exec(
        select(ContribRequest)
        .where(ContribRequest.id == request_id)
        .where(ContribRequest.project_id == project.id)
    ).first()
    if req is None:
        raise HTTPException(404, "Request not found")
    for field in ("title", "message", "due_at", "expires_at", "max_responses"):
        value = getattr(req_in, field)
        if value is not None:
            setattr(req, field, value)
    if req_in.closed is not None:
        req.closed_at = utcnow() if req_in.closed else None
    if req_in.revoked is not None:
        req.revoked = req_in.revoked
    session.add(req)
    session.commit()
    session.refresh(req)
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    wdir = str(repo.working_dir)
    try:
        record = calkit.contrib.load(str(req.id), wdir=wdir)
    except FileNotFoundError:
        record = _record(req, req.created_by)
    fresh = _record(req, req.created_by)
    record.title, record.message = fresh.title, fresh.message
    record.due, record.expires, record.status = (
        fresh.due,
        fresh.expires,
        fresh.status,
    )
    repo.git.add(calkit.contrib.save(record, wdir=wdir))
    verb = "Revoke" if req.revoked else "Close" if req.closed_at else "Update"
    commit_staged(
        project, repo, session, f"{verb} review request for {req.target_path}"
    )
    return _public(req)


def _get_request_by_token(session: SessionDep, token: str) -> ContribRequest:
    req = session.exec(
        select(ContribRequest).where(
            ContribRequest.token_hash == _hash_token(token)
        )
    ).first()
    if req is None:
        raise HTTPException(404, "This link isn't valid")
    return req


@router.get("/contrib-requests/{token}")
def get_contrib_request_by_token(
    token: str, session: SessionDep, current_user: CurrentUserOptional
) -> ContribRequestView:
    """What the recipient of a link sees: the ask, and whether they can
    still answer it."""
    req = _get_request_by_token(session, token)
    project = req.project
    req.view_count += 1
    session.add(req)
    session.commit()
    requester = req.created_by
    return ContribRequestView(
        title=req.title,
        message=req.message,
        direction=req.direction,
        target_kind=req.target_kind,
        target_path=req.target_path,
        document_path=req.document_path,
        git_ref=req.git_ref,
        git_rev_abbrev=req.git_rev[:7] if req.git_rev else None,
        permission=req.permission,
        identity_requirement=req.identity_requirement,
        approval_status=req.approval_status,
        due_at=req.due_at,
        round=req.round,
        expires_at=req.expires_at,
        created=req.created,
        owner_account_name=project.owner_account_name,
        owner_account_display_name=project.owner_account.display_name
        or project.owner_account_name,
        project_name=project.name,
        project_title=project.title or project.name,
        requester_name=(
            requester.full_name or requester.email if requester else "Someone"
        ),
        responder_email=req.email,
        identity_confirmed=req.identity_requirement == "anonymous"
        or (current_user is not None and current_user.email == req.email),
        can_respond=req.is_open and req.permission != "view",
    )


@router.get("/contrib-requests/{token}/document")
def get_contrib_request_document(token: str, session: SessionDep) -> Response:
    """The document that went out with the request, e.g., the Word copy."""
    req = _get_request_by_token(session, token)
    if not req.document_path:
        raise HTTPException(404, "No document was attached to this request")
    if req.revoked or req.is_expired:
        raise HTTPException(403, "This link is no longer active")
    project = req.project
    repo = get_repo(
        project=project, user=req.created_by, session=session, ttl=None
    )
    tree = get_repo_tree_for_ref(repo, None)
    data = app.projects.read_project_file(
        project=project,
        tree=tree,
        path=req.document_path,
        max_bytes=MAX_DOCUMENT_BYTES,
    )
    name = os.path.basename(req.document_path)
    return Response(
        content=data,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/contrib-requests/{token}/responses")
def post_contrib_request_response(
    token: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    file: Annotated[UploadFile, File()],
    responder_name: Annotated[str | None, Form()] = None,
    responder_email: Annotated[str | None, Form()] = None,
    message: Annotated[str | None, Form()] = None,
) -> ContribResponsePublic:
    """Hand a reviewed document back.

    It's saved to the project under ``reviews/`` and committed on behalf
    of whoever sent the request, authored by the reviewer, and recorded
    against the request in the repo and here.
    """
    req = _get_request_by_token(session, token)
    if not req.is_open:
        raise HTTPException(403, "This request is no longer open")
    if req.permission == "view":
        raise HTTPException(403, "This request doesn't accept responses")
    name = (responder_name or "").strip() or req.contributor_name
    email = (responder_email or "").strip().lower() or req.email
    if current_user is not None:
        name = name or current_user.full_name
        email = email or current_user.email
    if req.identity_requirement == "account" and current_user is None:
        raise HTTPException(401, "Sign in to respond to this request")
    if req.identity_requirement == "email" and not email:
        raise HTTPException(400, "An email address is required")
    if req.created_by is None:
        raise HTTPException(500, "This request has no sender to commit as")
    project = req.project
    data = read_upload(file)
    repo = get_repo(
        project=project, user=req.created_by, session=session, ttl=None
    )
    slug = re.sub(r"[^\w]+", "-", (name or email or "reviewer").split("@")[0])
    base = req.document_path or file.filename or "review.docx"
    path, wdir = stage_review(
        project, repo, default_review_path(base, suffix=slug), data
    )
    resp = ContribRequestResponse(
        request_id=req.id,
        user_id=current_user.id if current_user else None,
        responder_name=name,
        responder_email=email,
        email_verified=current_user is not None
        and current_user.email == email,
        status="submitted",
        via="hub",
        message=(message or "").strip() or None,
        git_rev=req.git_rev,
        submitted_at=utcnow(),
    )
    session.add(resp)
    session.commit()
    session.refresh(resp)
    attachment = ContribAttachment(
        response_id=resp.id,
        filename=path,
        content_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        size_bytes=len(data),
        storage_key=path,
        uploaded_by_user_id=current_user.id if current_user else None,
    )
    session.add(attachment)
    session.commit()
    try:
        record = calkit.contrib.load(str(req.id), wdir=wdir)
    except FileNotFoundError:
        record = _record(req, req.created_by)
    record.responses.append(
        ContribResponseRecord(
            path=path,
            name=name,
            email=email,
            message=resp.message,
            received=resp.submitted_at or utcnow(),
        )
    )
    repo.git.add(calkit.contrib.save(record, wdir=wdir))
    author = None
    if name and email:
        author = f"{name} <{email}>"
    elif email:
        author = f"{email} <{email}>"
    commit_staged(
        project,
        repo,
        session,
        f"Add review of {req.target_path} from {name or email or 'reviewer'}",
        author=author,
    )
    session.refresh(resp)
    return _response_public(resp)
