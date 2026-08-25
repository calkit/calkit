"""Fetching imported data into a project checkout.

A dataset declared as imported from a DOI, a URL, or a Git repo is only
useful once the bytes are in the project. These helpers bring them in, so
that declaring an import on the hub means the same thing it means from the
CLI: the data is there, tracked, and its origin is recorded.
"""

import logging
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
from urllib.parse import unquote, urlparse

import requests
from fastapi import HTTPException

import calkit.invenio

logger = logging.getLogger(__name__)

# Generous for research data, still bounded: the request holds a worker.
MAX_DOWNLOAD_BYTES = 2_000_000_000
DOWNLOAD_TIMEOUT_S = 120
CHUNK = 1024 * 1024


def _filename_from_url(url: str, resp: requests.Response) -> str:
    disposition = resp.headers.get("content-disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition)
    if match:
        return posixpath.basename(unquote(match.group(1).strip()))
    name = posixpath.basename(unquote(urlparse(url).path))
    return name or "download"


def download_to(
    url: str, dest: str, max_bytes: int = MAX_DOWNLOAD_BYTES
) -> int:
    """Stream a URL to a file, refusing anything over the size cap.

    Returns the number of bytes written. A cap rather than trusting the
    Content-Length header, since the header can be missing or wrong.
    """
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    total = 0
    try:
        with requests.get(
            url, stream=True, timeout=DOWNLOAD_TIMEOUT_S
        ) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=CHUNK):
                    total += len(chunk)
                    if total > max_bytes:
                        raise HTTPException(
                            413,
                            f"{url} is larger than the {max_bytes // 10**9} GB "
                            "limit for fetching through the hub",
                        )
                    f.write(chunk)
    except HTTPException:
        if os.path.isfile(dest):
            os.remove(dest)
        raise
    except requests.RequestException as e:
        if os.path.isfile(dest):
            os.remove(dest)
        raise HTTPException(502, f"Could not download {url}: {e}")
    return total


DOI_PREFIX_RE = re.compile(
    r"^(?:https?://)?(?:www\.|dx\.)?doi\.org/|^doi:\s*", re.IGNORECASE
)
DOI_URL_RE = re.compile(
    r"^https?://(?:www\.|dx\.)?doi\.org/(10\.\S+)$", re.IGNORECASE
)


def normalize_doi(value: str) -> str:
    """The bare DOI, whatever form it was pasted in.

    `https://doi.org/10.x`, `dx.doi.org/10.x`, `doi:10.x`, and surrounding
    whitespace all reduce to `10.x`, which is the identifier itself and the
    only form worth recording.
    """
    return DOI_PREFIX_RE.sub("", value.strip()).strip()


def doi_from_url(url: str) -> str | None:
    """The DOI a doi.org link points at, or None for any other URL."""
    match = DOI_URL_RE.match(url.strip())
    return match.group(1) if match else None


def resolve_doi_files(doi: str) -> dict[str, str]:
    """The files behind a DOI, as name -> download URL.

    Zenodo and Figshare expose their records through APIs; anything else is
    resolved through doi.org and accepted only when it lands on a file
    rather than a landing page.
    """
    doi = normalize_doi(doi)
    zenodo = re.fullmatch(r"10\.5281/zenodo\.(\d+)", doi)
    if zenodo:
        try:
            urls: dict[str, str] = calkit.invenio.get_download_urls(
                zenodo.group(1), service="zenodo", auth=False
            )
            return urls
        except Exception as e:
            raise HTTPException(502, f"Could not read Zenodo record: {e}")
    if doi.startswith("10.6084/"):
        try:
            resp = requests.get(
                "https://api.figshare.com/v2/articles",
                params={"doi": doi},
                timeout=30,
            )
            resp.raise_for_status()
            articles = resp.json()
            if not articles:
                raise HTTPException(
                    404, f"No Figshare article found for {doi}"
                )
            files_resp = requests.get(
                f"https://api.figshare.com/v2/articles/{articles[0]['id']}/files",
                timeout=30,
            )
            files_resp.raise_for_status()
            return {f["name"]: f["download_url"] for f in files_resp.json()}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"Could not read Figshare record: {e}")
    # Anything else: follow the DOI and see whether it resolves to a file
    try:
        head = requests.head(
            f"https://doi.org/{doi}", allow_redirects=True, timeout=30
        )
    except requests.RequestException as e:
        raise HTTPException(502, f"Could not resolve DOI {doi}: {e}")
    content_type = head.headers.get("content-type", "").lower()
    if head.ok and content_type and not content_type.startswith("text/html"):
        return {_filename_from_url(head.url, head): head.url}
    raise HTTPException(
        400,
        f"Couldn't find files to download for {doi}. Zenodo and Figshare "
        "records work directly; for other archives, use the URL option "
        "with a direct link to the file.",
    )


def fetch_files(
    files: dict[str, str], repo_dir: str, path: str
) -> tuple[str, list[str]]:
    """Download files into a project path, which is a file or a folder.

    One file goes to `path` when `path` names a file (has a suffix). A
    record with several files is a folder, whatever the path looked like:
    a file-looking path has its suffix dropped rather than becoming a
    folder called `record.csv`. Returns the path actually used and the
    repo-relative paths written under it.
    """
    if not files:
        raise HTTPException(404, "The source has no files to download")
    looks_like_file = bool(posixpath.splitext(path)[1])
    if len(files) == 1 and looks_like_file:
        (url,) = files.values()
        download_to(url, os.path.join(repo_dir, path))
        return path, [path]
    folder = posixpath.splitext(path)[0] if looks_like_file else path
    written: list[str] = []
    for name, url in files.items():
        rel = posixpath.join(folder, posixpath.basename(name))
        download_to(url, os.path.join(repo_dir, rel))
        written.append(rel)
    return folder, written


def fetch_git_path(
    repo_url: str,
    rev: str | None,
    src_path: str | None,
    repo_dir: str,
    dest: str,
) -> str:
    """Copy a path (or the whole tree) from another Git repo at a commit.

    A blobless clone keeps this cheap for a large repo; the checkout of the
    one path is what actually pulls bytes. With no ``rev`` the default
    branch's head is used. Returns the commit actually checked out, which
    is what gets recorded: a branch name would drift, a commit doesn't.
    """
    with tempfile.TemporaryDirectory() as tmp:
        clone = os.path.join(tmp, "src")
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    repo_url,
                    clone,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=DOWNLOAD_TIMEOUT_S,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    clone,
                    "checkout",
                    rev or "HEAD",
                    "--",
                    src_path or ".",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=DOWNLOAD_TIMEOUT_S,
            )
            commit = subprocess.run(
                ["git", "-C", clone, "rev-parse", rev or "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=DOWNLOAD_TIMEOUT_S,
            ).stdout.strip()
        except subprocess.CalledProcessError as e:
            raise HTTPException(
                400,
                f"Could not fetch {src_path or 'the repo'} at {rev} from "
                f"{repo_url}: {e.stderr.strip()}",
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, f"Timed out fetching from {repo_url}")
        source = os.path.join(clone, src_path) if src_path else clone
        if not os.path.exists(source):
            raise HTTPException(
                404, f"{src_path} is not in {repo_url} at {rev}"
            )
        target = os.path.join(repo_dir, dest)
        os.makedirs(os.path.dirname(target) or repo_dir, exist_ok=True)
        if os.path.isdir(source):
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns(".git"),
                dirs_exist_ok=True,
            )
        else:
            shutil.copy2(source, target)
    return commit
