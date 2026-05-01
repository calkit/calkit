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

import git

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


def create_citation_cff(
    ck_info: dict, release_name: str, release_date: str
) -> dict:
    """Create content to put in a CITATION.cff file."""
    content = {
        "cff-version": "1.2.0",
        "message": (
            "If you use these files, please cite is using these metadata."
        ),
        "title": ck_info.get("title"),
        "abstract": ck_info.get("description"),
        "version": release_name,
        "date-released": str(release_date),
        "repository-code": ck_info.get("git_repo_url"),
    }
    # Get authors from ck_info
    authors = ck_info.get("authors", [])
    cff_authors = []
    for author in authors:
        cff_author = {
            "family-names": author["last_name"],
            "given-names": author["first_name"],
        }
        if "orcid" in author:
            cff_author["orcid"] = author["orcid"]
        cff_authors.append(cff_author)
    content["authors"] = cff_authors
    # Get DOIs from ck_info
    ids = []
    for rname, release in ck_info["releases"].items():
        if release["kind"] == "project" and "doi" in release:
            ids.append(
                {
                    "description": f"Release {rname}",
                    "type": "doi",
                    "value": release["doi"],
                }
            )
    content["identifiers"] = ids
    return content


def ls_files() -> list[str]:
    """List all files to be released."""
    repo = git.Repo()
    git_files = repo.git.ls_files(".", recurse_submodules=True).splitlines()
    dvc_files = calkit.dvc.list_paths(recursive=True)
    cache_files: list[str] = []
    cache_root = os.path.join(".dvc", "cache")
    if os.path.isdir(cache_root):
        for root, _, files in os.walk(cache_root):
            for filename in files:
                fpath = os.path.join(root, filename)
                if os.path.isfile(fpath):
                    cache_files.append(fpath)
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
                            str(abs_fpath.relative_to(repo_root))
                        )
        elif abs_workspace.exists():
            raise ValueError(
                f"dvc-zip workspace path {workspace_path!r} exists but is "
                "not a directory; this may indicate a bug or tampering with "
                ".calkit/zip/paths.json"
            )
    return list(
        dict.fromkeys(git_files + dvc_files + cache_files + dvc_zip_files)
    )


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
