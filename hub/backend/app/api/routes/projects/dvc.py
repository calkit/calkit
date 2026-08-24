"""Routes for the Calkit HTTP DVC remote."""

import functools
import hashlib
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

import app.projects
from app import mixpanel
from app.api.deps import CurrentUserDvcScope, SessionDep
from app.config import settings
from app.models import Message
from app.storage import (
    get_data_prefix,
    get_object_fs,
    get_storage_usage,
    invalidate_storage_usage_cache,
    make_data_fpath,
    remove_gcs_content_type,
)

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@router.post("/projects/{owner_name}/{project_name}/dvc/files/md5/{idx}/{md5}")
async def post_project_dvc_file(
    *,
    owner_name: str,
    project_name: str,
    idx: str,
    md5: str,
    session: SessionDep,
    current_user: CurrentUserDvcScope,
    req: Request,
) -> Message:
    owner_name = owner_name.lower()
    project_name = project_name.lower()
    mixpanel.user_dvc_pushed(
        user=current_user, owner_name=owner_name, project_name=project_name
    )
    logger.info(
        f"Received request from {current_user.email} to post "
        f"DVC file MD5 {idx}{md5}"
    )
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    logger.info(f"{current_user.email} requesting to POST data")
    # Check if user has not exceeded their storage limit
    fs = get_object_fs()
    owner = project.owner
    if owner is None or owner.subscription is None:
        raise HTTPException(400, "Project owner subscription not configured")
    storage_limit_gb = owner.subscription.storage_limit
    session.close()
    # Create bucket if it doesn't exist -- only necessary with MinIO
    if settings.ENVIRONMENT == "local" and not fs.exists(get_data_prefix()):
        fs.makedir(get_data_prefix())
    storage_used_gb = get_storage_usage(owner_name, fs=fs)
    logger.info(
        f"{owner_name} has used {storage_used_gb}/{storage_limit_gb} "
        "GB of storage"
    )
    if storage_used_gb > storage_limit_gb:
        logger.info("Rejecting request due to storage limit exceeded")
        mixpanel.user_out_of_storage(user=current_user)
        raise HTTPException(400, "Storage limit exceeded")
    fpath = make_data_fpath(
        owner_name=owner_name, project_name=project_name, idx=idx, md5=md5
    )
    # Use a pending path during upload so we can rename after
    sig = hashlib.md5()
    pending_fpath = fpath + ".pending"
    upload_succeeded = False
    try:
        with fs.open(pending_fpath, "wb") as f:
            # See https://stackoverflow.com/q/73322065/2284865
            async for chunk in req.stream():
                f.write(chunk)  # type: ignore
                sig.update(chunk)
        # If using Google Cloud Storage, we need to remove the content type
        # metadata in order to set it for signed URLs
        if settings.ENVIRONMENT != "local":
            remove_gcs_content_type(pending_fpath)
        digest = sig.hexdigest()
        logger.info(f"Computed MD5 from DVC post: {digest}")
        if md5.endswith(".dir"):
            digest += ".dir"
        if digest == idx + md5:
            logger.info("MD5 matches; removing pending suffix")
            fs.mv(pending_fpath, fpath)
            upload_succeeded = True
            invalidate_storage_usage_cache(owner_name)
        else:
            logger.warning("MD5 does not match")
            raise HTTPException(400, "MD5 does not match")
    finally:
        if not upload_succeeded:
            try:
                if fs.exists(pending_fpath):
                    fs.rm(pending_fpath)
            except Exception:
                logger.exception(
                    "Failed to remove pending DVC upload %s", pending_fpath
                )
    return Message(message="Success")


@router.get("/projects/{owner_name}/{project_name}/dvc/files/md5/{idx}/{md5}")
async def get_project_dvc_file(
    *,
    owner_name: str,
    project_name: str,
    idx: str,
    md5: str,
    session: SessionDep,
    current_user: CurrentUserDvcScope,
) -> StreamingResponse:
    owner_name = owner_name.lower()
    project_name = project_name.lower()
    mixpanel.user_dvc_pulled(
        user=current_user, owner_name=owner_name, project_name=project_name
    )
    logger.info(f"{current_user.email} requesting to GET data")
    app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    # Release the DB connection before streaming: FastAPI finalizes the
    # session dependency only after the response body is fully sent, so an
    # open session would pin a pool connection (idle in transaction) for the
    # entire download. The POST route closes early for the same reason.
    session.close()
    # If file doesn't exist, return 404
    fs = get_object_fs()
    fpath = make_data_fpath(
        owner_name=owner_name, project_name=project_name, idx=idx, md5=md5
    )
    logger.info(f"Checking for {fpath}")
    if not fs.exists(fpath):
        logger.info(f"{fpath} does not exist")
        raise HTTPException(404)

    # Stream the file contents back to the user
    def iterfile():
        with fs.open(fpath, "rb") as f:
            chunker = functools.partial(f.read, 4_000_000)
            for chunk in iter(chunker, b""):
                yield chunk

    return StreamingResponse(iterfile())
