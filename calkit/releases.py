"""Functionality related to releases.

For more information on the citation file format, see:
https://github.com/citation-file-format/citation-file-format
"""

import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Literal

import calkit
import calkit.dvc.zip

SERVICES = {
    "caltechdata": {"name": "CaltechDATA", "url": "https://data.caltech.edu"},
    "zenodo": {"name": "Zenodo", "url": "https://zenodo.org"},
}

BIBTEX_TEMPLATE = """
@misc{{{entry_key},
  author       = {{{authors}}},
  title        = {{{title}}},
  month        = {month},
  year         = {{{year}}},
  publisher    = {{{service}}},
  doi          = {{{doi}}},
  url          = {{https://doi.org/{doi}}},
}}
""".strip()


def _sanitize_bibtex_key(value: str) -> str:
    """Return a BibTeX-safe key fragment."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return safe or "release"


def _escape_bibtex_value(value: str | int | None) -> str:
    """Escape braces and backslashes to keep generated entries parseable."""
    if value is None:
        return ""
    value = str(value)
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def create_bibtex(
    authors: list[dict],
    release_date: str,
    title: str | None,
    doi: str | None,
    record_id: int | str | None,
    service: Literal["zenodo", "caltechdata"] = "zenodo",
) -> str:
    """Create a BibTeX entry for a release."""
    first_author_last_name = authors[0]["last_name"]
    authors_string = f"{authors[0]['last_name']}, {authors[0]['first_name']}"
    if len(authors) > 1:
        for author in authors[1:]:
            authors_string += (
                f" and {author['last_name']}, {author['first_name']}"
            )
    year, month, _ = release_date.split("-")
    month = int(month)
    year = int(year)
    if record_id is None:
        record_id = "draft"
    if doi is None:
        doi = "10.0000/dry-run"
    entry_key = (
        f"{_sanitize_bibtex_key(first_author_last_name)}"
        f"{year}_{_sanitize_bibtex_key(str(record_id))}"
    )
    return BIBTEX_TEMPLATE.format(
        entry_key=entry_key,
        authors=_escape_bibtex_value(authors_string),
        title=_escape_bibtex_value(title),
        doi=_escape_bibtex_value(doi),
        month=month,
        year=year,
        service=SERVICES[service]["name"],
    )


CITATION_CFF_TEMPLATE = """
cff-version: 1.2.0
message: If you use this software, please cite it using these metadata.
title: My Research Software
abstract: This is my awesome research software. It does many things.
authors:
  - family-names: Druskat
    given-names: Stephan
    orcid: "https://orcid.org/1234-5678-9101-1121"
  - name: "The Research Software project"
version: 0.11.2
date-released: "2021-07-18"
identifiers:
  - description: This is the collection of archived snapshots of all versions of My Research Software
    type: doi
    value: "10.5281/zenodo.123456"
  - description: This is the archived snapshot of version 0.11.2 of My Research Software
    type: doi
    value: "10.5281/zenodo.123457"
license: Apache-2.0
repository-code: "https://github.com/citation-file-format/my-research-software"
""".strip()


def to_cff_author(author: dict) -> dict:
    """Convert a Calkit author dict to a CITATION.cff author entry."""
    cff_author = {
        "family-names": author["last_name"],
        "given-names": author.get("first_name", ""),
    }
    if author.get("affiliation"):
        cff_author["affiliation"] = author["affiliation"]
    orcid = author.get("orcid")
    if orcid:
        # CITATION.cff expects the ORCID as a full URL
        if not str(orcid).startswith("http"):
            orcid = f"https://orcid.org/{orcid}"
        cff_author["orcid"] = orcid
    return cff_author


def set_cff_authors(
    authors: list[dict],
    ck_info: dict | None = None,
    path: str = "CITATION.cff",
) -> dict:
    """Write authors into a CITATION.cff file, creating it if necessary.

    Existing content (and any fields we don't manage) is preserved. Returns
    the resulting CITATION.cff content.
    """
    content: dict = {}
    if os.path.isfile(path):
        with open(path) as f:
            loaded = calkit.ryaml.load(f)
        if isinstance(loaded, dict):
            content = loaded
    content.setdefault("cff-version", "1.2.0")
    content.setdefault(
        "message",
        "If you use these files, please cite them using these metadata.",
    )
    if ck_info is not None and ck_info.get("title") is not None:
        content.setdefault("title", ck_info.get("title"))
    content["authors"] = [to_cff_author(a) for a in authors]
    with open(path, "w") as f:
        calkit.ryaml.dump(content, f)
    return content


def create_citation_cff(
    ck_info: dict,
    release_name: str,
    release_date: str,
    authors: list[dict] | None = None,
    path: str = "CITATION.cff",
) -> dict:
    """Create content to put in a CITATION.cff file.

    CITATION.cff is the single source of truth for authors, so if a file
    already exists its ``authors`` block is preserved as-is. Only when no
    authors are present is the provided ``authors`` list (in Calkit format)
    used to populate them.
    """
    content: dict = {}
    if os.path.isfile(path):
        with open(path) as f:
            loaded = calkit.ryaml.load(f)
        if isinstance(loaded, dict):
            content = loaded
    content["cff-version"] = "1.2.0"
    content.setdefault(
        "message",
        "If you use these files, please cite them using these metadata.",
    )
    if ck_info.get("title") is not None:
        content["title"] = ck_info.get("title")
    if ck_info.get("description") is not None:
        content["abstract"] = ck_info.get("description")
    content["version"] = release_name
    content["date-released"] = str(release_date)
    if ck_info.get("git_repo_url") is not None:
        content["repository-code"] = ck_info.get("git_repo_url")
    # Preserve existing authors (the source of truth); otherwise populate
    # from the provided Calkit-format author list
    if not content.get("authors"):
        content["authors"] = [to_cff_author(a) for a in (authors or [])]
    # Get DOIs from ck_info releases
    ids = []
    for rname, release in ck_info.get("releases", {}).items():
        if release.get("kind") == "project" and "doi" in release:
            ids.append(
                {
                    "description": f"Release {rname}",
                    "type": "doi",
                    "value": release["doi"],
                }
            )
    content["identifiers"] = ids
    return content


def read_authors_from_cff(path: str = "CITATION.cff") -> list[dict]:
    """Read authors from a ``CITATION.cff`` file into Calkit author dicts.

    The citation file format stores names as ``given-names``/``family-names``
    and ORCIDs as full URLs, whereas Calkit uses ``first_name``/``last_name``
    and bare ORCID identifiers, so values are normalized here.
    Authors without a family name (e.g., entity authors that only have a
    ``name`` field) are skipped because they cannot be expressed as a
    personal creator.
    """
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        cff = calkit.ryaml.load(f)
    if not isinstance(cff, dict):
        return []
    authors = []
    for cff_author in cff.get("authors", []) or []:
        if not isinstance(cff_author, dict):
            continue
        last_name = cff_author.get("family-names")
        if not last_name:
            # Entity authors only have a "name"; skip since we can't build a
            # personal creator from them
            continue
        author = {
            "first_name": cff_author.get("given-names", ""),
            "last_name": last_name,
        }
        affiliation = cff_author.get("affiliation")
        if affiliation:
            author["affiliation"] = affiliation
        orcid = cff_author.get("orcid")
        if orcid:
            # CFF stores ORCID as a full URL; store the bare identifier
            author["orcid"] = re.sub(r"^https?://orcid\.org/", "", str(orcid))
        authors.append(author)
    return authors


def ls_files() -> list[str]:
    """List all files to be released."""
    repo = calkit.git.get_repo()
    git_files = repo.git.ls_files(".", recurse_submodules=True).splitlines()
    dvc_files = calkit.dvc.list_paths(recursive=True)
    cache_files: list[str] = []
    cache_root = os.path.join(".dvc", "cache")
    if os.path.isdir(cache_root):
        for root, _, files in os.walk(cache_root):
            for filename in files:
                fpath = os.path.join(root, filename)
                if os.path.isfile(fpath):
                    cache_files.append(Path(fpath).as_posix())
    # Include files from unzipped dvc-zip workspace folders, which are
    # ignored by both Git and DVC and would otherwise be missing from the
    # release archive
    dvc_zip_files: list[str] = []
    repo_root = Path(repo.working_dir).resolve()
    zip_path_map = calkit.dvc.zip.get_zip_path_map()
    for workspace_path in zip_path_map:
        abs_workspace = (repo_root / workspace_path).resolve()
        if not abs_workspace.is_relative_to(repo_root):
            raise ValueError(
                f"dvc-zip workspace path {workspace_path!r} is not within "
                "the repository root; this may indicate a bug or tampering "
                "with .calkit/zip/paths.json"
            )
        if abs_workspace.is_dir():
            for root, _, files in os.walk(abs_workspace):
                for filename in files:
                    abs_fpath = Path(root) / filename
                    if abs_fpath.is_file():
                        dvc_zip_files.append(
                            abs_fpath.relative_to(repo_root).as_posix()
                        )
        elif abs_workspace.exists():
            raise ValueError(
                f"dvc-zip workspace path {workspace_path!r} exists but is "
                "not a directory; this may indicate a bug or tampering with "
                ".calkit/zip/paths.json"
            )
    zip_files = {Path(p).as_posix() for p in zip_path_map.values()}
    return [
        f
        for f in dict.fromkeys(
            git_files + dvc_files + cache_files + dvc_zip_files
        )
        if Path(f).as_posix() not in zip_files
    ]


def make_dvc_md5s(
    zipfile: str | None = None, paths: list[str] | None = None
) -> dict:
    """Create a dictionary of DVC tracked files for a release, keyed by MD5
    so we can iterate through them and populate the cache from a release
    archive.
    """
    dvc_files = calkit.dvc.list_files()
    resp = {}
    for f in dvc_files:
        if paths and f["path"] not in paths:
            continue
        resp[f["md5"]] = dict(path=f["path"], zipfile=zipfile)
    return resp


def zip_paths(zip_path: str, paths: list[str]) -> None:
    """Create a compressed ZIP from a list of file or directory paths."""
    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zipf:
        for path in paths:
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for filename in files:
                        fpath = os.path.join(root, filename)
                        zipf.write(fpath)
            elif os.path.isfile(path):
                zipf.write(path)


def populate_dvc_cache():
    """Populate DVC cache from releases."""
    ck_info = calkit.load_calkit_info()
    releases = ck_info.get("releases", {})
    for name, _ in releases.items():
        md5s_fpath = f".calkit/releases/{name}/dvc-md5s.yaml"
        with open(md5s_fpath) as f:
            md5s = calkit.ryaml.load(f)
        # TODO: If we don't have MD5s, create them
        for md5, obj in md5s.items():
            dvc_cache_fpath = f".dvc/cache/files/md5/{md5[:2]}/{md5[2:]}"
            if not os.path.isfile(dvc_cache_fpath):
                # TODO: Download file from Zenodo and save in the cache
                release_fpath = f".calkit/releases/{name}/files/{obj['path']}"
                print(release_fpath)
                zip_file = obj.get("zipfile")
                if zip_file is not None:
                    zip_fpath = f".calkit/releases/{name}/files/{zip_file}"
                    print(zip_fpath)
                # Extract out of ZIP file if necessary
                # TODO: Check MD5 before inserting into the cache


def check_project_release_archive(
    zip_path: str, verbose: bool = False
) -> None:
    """Ensure an extracted project release archive can run cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(zip_path) as zipf:
            zipf.extractall(tmpdir)
        ck_info = calkit.load_calkit_info(wdir=tmpdir)
        has_pipeline = bool(ck_info.get("pipeline")) or os.path.isfile(
            os.path.join(tmpdir, "dvc.yaml")
        )
        if not has_pipeline:
            return
        cmd = [sys.executable, "-m", "calkit", "run"]
        if verbose:
            cmd.append("--verbose")
        try:
            subprocess.run(cmd, cwd=tmpdir, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                "Released project archive failed pipeline checks: "
                "`calkit run` failed."
            ) from e
