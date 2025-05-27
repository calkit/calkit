"""Functionality related to releases.

For more information on the citation file format, see:
https://github.com/citation-file-format/citation-file-format
"""

import os

import git

import calkit

BIBTEX_TEMPLATE = """
@misc{{{first_author_last_name}{year}_{dep_id},
  author       = {{{authors}}},
  title        = {{{title}}},
  month        = {month},
  year         = {{{year}}},
  publisher    = {{Zenodo}},
  doi          = {{{doi}}},
  url          = {{https://doi.org/{doi}}},
}}
""".strip()


def create_bibtex(
    authors: list[dict], release_date: str, title: str, doi: str, dep_id: int
) -> str:
    """Create a BibTeX entry for a Zenodo release."""
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
    return BIBTEX_TEMPLATE.format(
        first_author_last_name=first_author_last_name,
        authors=authors_string,
        title=title,
        doi=doi,
        month=month,
        year=year,
        dep_id=dep_id,
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
        "title": ck_info["title"],
        "abstract": ck_info["description"],
        "version": release_name,
        "date-released": str(release_date),
        "repository-code": ck_info["git_repo_url"],
    }
    # Get authors from ck_info
    authors = ck_info["authors"]
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
    git_files = repo.git.ls_files(".").strip().split("\n")
    dvc_files = calkit.dvc.list_paths(recursive=True)
    return git_files + dvc_files


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


def populate_dvc_cache():
    """Populate DVC cache from releases."""
    ck_info = calkit.load_calkit_info()
    releases = ck_info.get("releases", {})
    for name, release in releases.items():
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
