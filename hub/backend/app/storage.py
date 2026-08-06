"""Functionality for managing object storage."""

import json
import os
from typing import Any, Literal

import boto3
import cachetools
import gcsfs
import s3fs
from botocore.config import Config
from google.cloud import storage as gcs
from google.oauth2 import service_account as gcs_service_account

from app.config import settings

# Multipart/chunked upload configuration
MULTIPART_THRESHOLD_BYTES = 64 * 1024 * 1024  # 64 MB
MULTIPART_PART_SIZE_BYTES = 16 * 1024 * 1024  # 16 MB
CHUNKED_CHUNK_SIZE_BYTES = 16 * 1024 * 1024  # 16 MB
S3_MAX_PARTS = 10000  # S3 multipart upload limit
STORAGE_USAGE_CACHE_TTL_SECONDS = 300
STORAGE_USAGE_CACHE_MAXSIZE = 2048

# In-process cache for owner-level storage usage reads
_storage_usage_cache: cachetools.TTLCache[str, float] = cachetools.TTLCache(
    maxsize=STORAGE_USAGE_CACHE_MAXSIZE,
    ttl=STORAGE_USAGE_CACHE_TTL_SECONDS,
)


def get_backend() -> Literal["s3", "gcs"]:
    """Get the configured storage backend for the current environment."""
    return "s3" if settings.ENVIRONMENT == "local" else "gcs"


def upload_should_be_chunked(content_length: int | None) -> bool:
    """Determine if an upload should use multipart/chunked strategy."""
    return (
        content_length is not None
        and content_length >= MULTIPART_THRESHOLD_BYTES
    )


def get_upload_chunk_size(backend: Literal["s3", "gcs"] | None = None) -> int:
    """Get the chunk/part size for the specified backend in bytes."""
    if backend is None:
        backend = get_backend()
    return (
        MULTIPART_PART_SIZE_BYTES
        if backend == "s3"
        else CHUNKED_CHUNK_SIZE_BYTES
    )


def get_gcs_credentials() -> dict | None:
    """Get GCS credentials from environment."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if creds_json:
        return json.loads(creds_json)
    return None


def get_gcs_client() -> gcs.Client:
    """Get a Google Cloud Storage client with credentials from environment."""
    creds_dict = get_gcs_credentials()
    if creds_dict:
        credentials = (
            gcs_service_account.Credentials.from_service_account_info(
                creds_dict
            )
        )
        return gcs.Client(credentials=credentials)
    return gcs.Client()


def remove_gcs_content_type(fpath):
    client = get_gcs_client()
    bucket = client.bucket(f"calkit-{settings.ENVIRONMENT}")
    blob = bucket.blob(fpath.removeprefix(f"gcs://{bucket.name}/"))
    blob.content_type = None
    blob.patch()


def get_object_fs() -> s3fs.S3FileSystem | gcsfs.GCSFileSystem:
    if settings.ENVIRONMENT == "local":
        return s3fs.S3FileSystem(
            endpoint_url="http://minio:9000",
            key="root",
            secret=os.getenv("MINIO_ROOT_PASSWORD"),
        )
    return gcsfs.GCSFileSystem(token=get_gcs_credentials())


def get_data_prefix() -> str:
    if settings.ENVIRONMENT == "local":
        return "s3://data"
    else:
        return f"gcs://calkit-{settings.ENVIRONMENT}/data"


def get_data_prefix_for_owner(owner_name: str, lowercase: bool = True) -> str:
    prefix = f"{get_data_prefix()}/{owner_name}"
    return prefix.lower() if lowercase else prefix


def make_data_fpath(
    owner_name: str,
    project_name: str,
    idx: str,
    md5: str,
    legacy: bool = False,
) -> str:
    """Make a data file path for a given owner, project, index, and md5 hash.

    This matches the DVC path structure used for storing data files, i.e.,
    under the files/md5 subdirectory.

    The legacy flag allows generating paths in the old format
    (without 'files/md5/') for backward compatibility with existing data.
    New uploads should use the new format.
    """
    prefix = get_data_prefix_for_owner(owner_name, lowercase=not legacy)
    if legacy:
        return f"{prefix}/{project_name}/{idx}/{md5}"
    else:
        return f"{prefix}/{project_name.lower()}/files/md5/{idx}/{md5}"


def _replace_local_object_host(url: str) -> str:
    if settings.ENVIRONMENT == "local":
        return url.replace(
            "http://minio:9000", f"http://objects.{settings.DOMAIN}"
        )
    return url


def _generate_multipart_urls(
    fpath: str,
    estimated_part_count: int,
    expires: int,
    fs: s3fs.S3FileSystem,
    content_type: str | None = None,
) -> dict:
    """Generate presigned URLs for S3 multipart upload.

    Returns a dict with:
    - bucket: bucket name
    - key: object key
    - upload_id: multipart upload ID
    - part_urls: list of presigned URLs for each part
    - complete_url: presigned URL to complete the upload
    - abort_url: presigned URL to abort the upload
    """
    # Parse bucket and key from fpath (e.g., "s3://bucket/path/to/object")
    if fpath.startswith("s3://"):
        bucket, _, key = fpath[5:].partition("/")
    else:
        raise ValueError(f"Invalid S3 path: {fpath}")
    s3_config = Config(
        signature_version="s3v4", s3={"addressing_style": "path"}
    )
    # Use an internal client for control-plane calls (create multipart upload)
    control_client: Any = boto3.client(
        "s3",
        endpoint_url=fs.endpoint_url,
        aws_access_key_id=fs.key,
        aws_secret_access_key=fs.secret,
        aws_session_token=fs.token,
        config=s3_config,
    )
    # Sign URLs for the externally reachable host to avoid host/signature
    # mismatch
    presign_endpoint = fs.endpoint_url
    if settings.ENVIRONMENT == "local":
        presign_endpoint = f"http://objects.{settings.DOMAIN}"
    presign_client: Any = boto3.client(
        "s3",
        endpoint_url=presign_endpoint,
        aws_access_key_id=fs.key,
        aws_secret_access_key=fs.secret,
        aws_session_token=fs.token,
        config=s3_config,
    )
    # Initiate multipart upload
    mpu = control_client.create_multipart_upload(
        Bucket=bucket,
        Key=key,
        **({"ContentType": content_type} if content_type else {}),
    )
    upload_id = mpu["UploadId"]
    # Generate presigned URLs for each part
    part_urls = []
    for part_number in range(1, estimated_part_count + 1):
        part_url = presign_client.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": bucket,
                "Key": key,
                "PartNumber": part_number,
                "UploadId": upload_id,
            },
            ExpiresIn=expires,
        )
        part_urls.append(part_url)
    # Generate presigned URL for completing the multipart upload
    complete_url = presign_client.generate_presigned_url(
        "complete_multipart_upload",
        Params={
            "Bucket": bucket,
            "Key": key,
            "UploadId": upload_id,
        },
        ExpiresIn=expires,
    )
    # Generate presigned URL for aborting the multipart upload
    abort_url = presign_client.generate_presigned_url(
        "abort_multipart_upload",
        Params={
            "Bucket": bucket,
            "Key": key,
            "UploadId": upload_id,
        },
        ExpiresIn=expires,
    )
    return {
        "bucket": bucket,
        "key": key,
        "upload_id": upload_id,
        "part_urls": part_urls,
        "complete_url": complete_url,
        "abort_url": abort_url,
    }


def get_object_url(
    fpath: str,
    fname: str | None = None,
    expires: int = 3600 * 24,
    fs: s3fs.S3FileSystem | gcsfs.GCSFileSystem | None = None,
    method: Literal["get", "put"] = "get",
    **kwargs,
) -> str:
    """Get a presigned URL for an object in object storage.

    For multipart/chunked uploads, use get_multipart_upload_info() instead.
    """
    if fs is None:
        fs = get_object_fs()
    # Standard presigned URL
    if isinstance(fs, s3fs.S3FileSystem):
        kws = {}
        if fname is not None:
            kws["ResponseContentDisposition"] = f"filename={fname}"
            if fname.endswith(".pdf"):
                kws["ResponseContentType"] = "application/pdf"
            elif fname.endswith(".html"):
                kws["ResponseContentType"] = "text/html"
            elif fname.endswith(".svg"):
                kws["ResponseContentType"] = "image/svg+xml"
        kws["client_method"] = f"{method}_object"
    elif isinstance(fs, gcsfs.GCSFileSystem):
        kws = {}
        if fname is not None:
            kws["response_disposition"] = f"filename={fname}"
            if fname.endswith(".pdf"):
                kws["response_type"] = "application/pdf"
            elif fname.endswith(".html"):
                kws["response_type"] = "text/html"
            elif fname.endswith(".svg"):
                kws["response_type"] = "image/svg+xml"
        kws["method"] = method.upper()
    else:
        raise ValueError("Unsupported filesystem type")
    signed_url = fs.sign(fpath, expiration=expires, **(kws | kwargs))
    if signed_url is None:
        raise RuntimeError("Failed to generate presigned URL")
    return _replace_local_object_host(signed_url)


def get_multipart_upload_info(
    fs: s3fs.S3FileSystem | gcsfs.GCSFileSystem,
    fpath: str,
    upload_size_bytes: int,
    expires: int = 900,
    content_type: str | None = None,
) -> dict:
    """Get multipart/chunked upload info with all presigned URLs.

    For S3: Returns dict with upload_id, bucket, key, part_urls, complete_url,
    abort_url
    For GCS: Returns dict with init_url for resumable upload

    Note: For S3, this creates a multipart upload server-side. If the client
    never completes or aborts, it will leave orphaned uploads. To prevent
    storage costs, configure S3 lifecycle rules to automatically clean up
    incomplete multipart uploads after a few days.
    The abort_url is provided to allow
    clients to explicitly clean up if they decide not to complete the upload.
    """
    if isinstance(fs, s3fs.S3FileSystem):
        part_size = get_upload_chunk_size("s3")
        estimated_part_count = (upload_size_bytes + part_size - 1) // part_size
        # Enforce S3's 10,000-part limit by dynamically increasing part size
        if estimated_part_count > S3_MAX_PARTS:
            part_size = (upload_size_bytes + S3_MAX_PARTS - 1) // S3_MAX_PARTS
            estimated_part_count = (
                upload_size_bytes + part_size - 1
            ) // part_size
        result = _generate_multipart_urls(
            fpath=fpath,
            estimated_part_count=estimated_part_count,
            expires=expires,
            fs=fs,
            content_type=content_type,
        )
        result["part_size_bytes"] = part_size
        return result
    elif isinstance(fs, gcsfs.GCSFileSystem):
        part_size = get_upload_chunk_size("gcs")
        estimated_part_count = (upload_size_bytes + part_size - 1) // part_size
        init_headers = {"x-goog-resumable": "start"}
        # Try POST first (preferred), fall back to PUT
        http_method = "POST"
        try:
            init_url = fs.sign(
                fpath,
                expiration=expires,
                method="POST",
                headers=init_headers,
            )
        except Exception:
            init_url = None
        if init_url is None:
            http_method = "PUT"
            init_url = fs.sign(
                fpath,
                expiration=expires,
                method="PUT",
                headers=init_headers,
            )
        if init_url is None:
            raise RuntimeError("Failed to generate chunked init URL")
        return {
            "init_url": init_url,
            "http_method": http_method,
            "estimated_chunk_count": estimated_part_count,
            "chunk_size_bytes": part_size,
        }
    else:
        raise ValueError("Unsupported filesystem type")


def get_storage_usage(
    owner_name: str, fs: s3fs.S3FileSystem | gcsfs.GCSFileSystem | None = None
) -> float:
    """Get storage usage in GB for a given owner."""
    cache_key = f"{settings.ENVIRONMENT}:{owner_name}"
    use_cache = fs is None
    if use_cache:
        cached = _storage_usage_cache.get(cache_key)
        if cached is not None:
            return cached
        fs = get_object_fs()
    assert fs is not None
    usage = fs.du(get_data_prefix_for_owner(owner_name))
    if isinstance(usage, dict):
        usage = sum(float(v) for v in usage.values())
    usage_gb = float(usage) / 1e9
    if use_cache:
        _storage_usage_cache[cache_key] = usage_gb
    return usage_gb


def invalidate_storage_usage_cache(owner_name: str | None = None) -> None:
    """Invalidate cached storage usage for one owner or all owners."""
    if owner_name is None:
        _storage_usage_cache.clear()
        return
    _storage_usage_cache.pop(f"{settings.ENVIRONMENT}:{owner_name}", None)


def migrate_legacy_dvc_paths(dry_run=True):
    """Migrate legacy DVC paths in object storage to new structure with
    'files/md5/'.
    """
    fs = get_object_fs()
    data_prefix = get_data_prefix()
    # Iterate over all owners and projects, renaming any two character folders
    # to prepend 'files/md5/' to match the new DVC path structure
    for owner_path in fs.ls(data_prefix, False):
        owner_name = os.path.basename(owner_path)
        owner_prefix = get_data_prefix_for_owner(owner_name, lowercase=False)
        for project_path in fs.ls(owner_prefix, False):
            project_name = os.path.basename(project_path)
            project_prefix = f"{owner_prefix}/{project_name}"
            for item_path in fs.ls(project_prefix, False):
                item_name = os.path.basename(item_path)
                if len(item_name) == 2 and all(c.isalnum() for c in item_name):
                    old_path = (
                        f"{data_prefix}/{owner_name}/{project_name}"
                        f"/{item_name}"
                    )
                    new_path = (
                        f"{data_prefix}/{owner_name}/{project_name}"
                        f"/files/md5/{item_name}"
                    )
                    print(f"Renaming {old_path} to {new_path}")
                    if not dry_run:
                        fs.mv(old_path, new_path, recursive=True)
            # Check that the path is lowercase
            if project_prefix != project_prefix.lower():
                old_path = f"{data_prefix}/{owner_name}/{project_name}"
                new_path = (
                    f"{data_prefix.lower()}/{owner_name.lower()}"
                    f"/{project_name.lower()}"
                )
                print(f"Renaming {old_path} to {new_path} to make lowercase")
                if not dry_run:
                    fs.mv(old_path, new_path, recursive=True)
