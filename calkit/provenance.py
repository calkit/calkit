"""Functionality for handling artifact provenance."""

import hashlib
import os
import tempfile

import requests

# The artifact kinds whose provenance is checked. Each entry must say where
# it came from: a pipeline stage, an import, or the person who created it,
# e.g., by collecting or measuring the data or drawing the figure.
PROVENANCE_ARTIFACT_TYPES = [
    "datasets",
    "figures",
    "publications",
    "tables",
    "presentations",
    "misc",
]


_CHUNK = 1024 * 1024


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_or_download_url(
    url: str,
    path: str,
    *,
    timeout: int = 120,
    max_bytes: int | None = None,
) -> tuple[bool, str]:
    """Return (downloaded, sha256).

    Downloads the URL to a temp file in the same directory as path.
    If path does not exist the temp file is moved into place.
    If path exists and matches the remote hash the temp file is removed.
    If path exists but differs an error is raised and the local file is
    left untouched.
    """
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    if os.path.isdir(path):
        raise ValueError(f"'{path}' is a directory, expected a file")
    tmp_fd, tmp_path = tempfile.mkstemp(dir=parent)
    try:
        h = hashlib.sha256()
        total = 0
        with requests.get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            with os.fdopen(tmp_fd, "wb") as f:
                tmp_fd = -1
                for chunk in resp.iter_content(chunk_size=_CHUNK):
                    total += len(chunk)
                    if max_bytes is not None and total > max_bytes:
                        raise ValueError(
                            f"{url} exceeds the {max_bytes} byte limit"
                        )
                    h.update(chunk)
                    f.write(chunk)
        remote_hash = h.hexdigest()
        if not os.path.exists(path):
            os.replace(tmp_path, path)
            return True, remote_hash
        local_hash = _sha256_file(path)
        if local_hash == remote_hash:
            os.remove(tmp_path)
            return False, remote_hash
        raise ValueError(
            f"Refusing to record URL provenance: {path} does not match "
            f"{url}\n\nLocal SHA-256:  {local_hash}\nRemote SHA-256: {remote_hash}"
        )
    except Exception:
        if tmp_fd != -1:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def has_provenance(artifact: dict) -> bool:
    """Return whether an artifact entry records where it came from.

    A stage and an import are the stronger forms, but ``created_by`` counts
    too: a dataset someone measured, or a schematic someone drew, is
    accounted for even though there's nothing upstream to point at. The
    field names in :class:`calkit.reproducibility.ReproCheck` predate
    attribution and are kept so callers reading them keep working.
    """
    return any(
        artifact.get(key) is not None
        for key in ["stage", "imported_from", "created_by"]
    )
