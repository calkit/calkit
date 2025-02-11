"""Functionality related to releases.

For more information on the citation file format, see:
https://github.com/citation-file-format/citation-file-format
"""

import subprocess

import git

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
"""


def ls_files() -> list[str]:
    """List all files to be released."""
    repo = git.Repo()
    git_files = repo.git.ls_files(".").strip().split("\n")
    dvc_files = (
        subprocess.check_output(["dvc", "ls", ".", "-R", "--dvc-only"])
        .decode()
        .strip()
        .split("\n")
    )
    return git_files + dvc_files
