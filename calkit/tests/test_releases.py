"""Tests for the ``releases`` module."""

import os
import subprocess
import sys
import zipfile

import bibtexparser
import git
import pytest

import calkit
from calkit.dvc.zip import write_zip_path_map
from calkit.releases import (
    add_bibtex_entry,
    add_doi_badge_to_readme,
    check_project_release_archive,
    create_bibtex,
    create_citation_cff,
    ls_files,
    read_authors_from_cff,
    set_cff_authors,
    zip_paths,
)


def test_ls_files(tmp_dir):
    subprocess.run(["calkit", "init"], check=True)
    # Create some files and add them to git and dvc
    (tmp_dir / "file1.txt").write_text("This is file 1.")
    (tmp_dir / "file2.txt").write_text("This is file 2.")
    subprocess.run(["git", "add", "file1.txt"], check=True)
    subprocess.run(["git", "commit", "-m", "Add file1.txt"], check=True)
    subprocess.run(["calkit", "dvc", "add", "file2.txt"], check=True)
    # Get the list of files to be released
    files = ls_files()
    assert "file1.txt" in files
    assert "file2.txt" in files
    # Now add some files in a git submodule and ensure they are included
    submodule_source = tmp_dir / "submodule-source"
    submodule_repo = git.Repo.init(submodule_source)
    (submodule_source / "submodule-file.txt").write_text(
        "This file lives in the submodule."
    )
    submodule_repo.git.add("submodule-file.txt")
    submodule_repo.index.commit("Add submodule file")
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(submodule_source),
            "submodule",
        ],
        check=True,
    )
    subprocess.run(["git", "commit", "-m", "Add submodule"], check=True)
    # Ensure all .dvc/cache content is included by ls_files.
    os.makedirs(".dvc/cache/aa", exist_ok=True)
    os.makedirs(".dvc/cache/files/md5/bb", exist_ok=True)
    os.makedirs(".dvc/cache/runs/cc/hash", exist_ok=True)
    (tmp_dir / ".dvc" / "cache" / "aa" / "legacy").write_text("x")
    (
        tmp_dir / ".dvc" / "cache" / "files" / "md5" / "bb" / "modern"
    ).write_text("y")
    (tmp_dir / ".dvc" / "cache" / "runs" / "cc" / "hash" / "run").write_text(
        "z"
    )
    files = ls_files()
    assert "submodule/submodule-file.txt" in files
    assert ".dvc/cache/aa/legacy" in files
    assert ".dvc/cache/files/md5/bb/modern" in files
    assert ".dvc/cache/runs/cc/hash/run" in files
    # Ensure files from unzipped dvc-zip workspace folders are included;
    # these folders are ignored by both Git and DVC
    (tmp_dir / "my-zip-workspace" / "sub").mkdir(parents=True, exist_ok=True)
    (tmp_dir / "my-zip-workspace" / "data.txt").write_text("data")
    (tmp_dir / "my-zip-workspace" / "sub" / "nested.txt").write_text("nested")
    # Create the zip file and DVC-track it so the exclusion filter is exercised
    zip_dir = tmp_dir / ".calkit" / "zip" / "files"
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_fpath = zip_dir / "my-zip-workspace.zip"
    with zipfile.ZipFile(zip_fpath, "w") as zf:
        zf.writestr("data.txt", "data")
        zf.writestr("sub/nested.txt", "nested")
    subprocess.run(
        ["calkit", "dvc", "add", str(zip_fpath.relative_to(tmp_dir))],
        check=True,
    )
    write_zip_path_map(
        {"my-zip-workspace": ".calkit/zip/files/my-zip-workspace.zip"}
    )
    files = ls_files()
    assert "my-zip-workspace/data.txt" in files
    assert "my-zip-workspace/sub/nested.txt" in files
    assert ".calkit/zip/files/my-zip-workspace.zip" not in files


def test_check_project_release_archive_passes_when_pipeline_is_current(
    tmp_dir, monkeypatch
):
    zip_path = "archive.zip"
    with zipfile.ZipFile(zip_path, "w") as zipf:
        zipf.writestr("calkit.yaml", "title: Test\n")
        zipf.writestr("dvc.yaml", "stages: {}\n")

    calls = []

    def fake_run(cmd, cwd=None, check=True):
        calls.append((cmd, cwd, check))

    monkeypatch.setattr("calkit.releases.subprocess.run", fake_run)
    check_project_release_archive(zip_path)
    assert len(calls) == 1
    assert calls[0][0] == [sys.executable, "-m", "calkit", "run"]
    assert calls[0][2] is True
    assert calls[0][1] is not None


def test_check_project_release_archive_fails_when_stages_out_of_date(
    tmp_dir, monkeypatch
):
    zip_path = "archive.zip"
    with zipfile.ZipFile(zip_path, "w") as zipf:
        zipf.writestr("calkit.yaml", "title: Test\n")
        zipf.writestr("dvc.yaml", "stages: {}\n")

    def fake_run(cmd, cwd=None, check=True):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr("calkit.releases.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="calkit run` failed"):
        check_project_release_archive(zip_path)


def test_create_bibtex():
    entry = create_bibtex(
        authors=[{"first_name": "Alice", "last_name": "Smith"}],
        release_date="2026-03-25",
        title="Test title",
        doi="10.1234/example",
        record_id="123",
    )
    entries = bibtexparser.loads(entry).entries
    assert len(entries) == 1
    entry = create_bibtex(
        authors=[{"first_name": "A", "last_name": "van der Waals"}],
        release_date="2026-03-25",
        title="Test title",
        doi="10.1234/example",
        record_id="abc-123",
    )
    entries = bibtexparser.loads(entry).entries
    assert len(entries) == 1
    entry = create_bibtex(
        authors=[{"first_name": "A", "last_name": "Smith"}],
        release_date="2026-03-25",
        title="Test title",
        doi=None,
        record_id=None,
    )
    entries = bibtexparser.loads(entry).entries
    assert len(entries) == 1


def test_add_bibtex_entry():
    new_entry = create_bibtex(
        authors=[{"first_name": "Jane", "last_name": "Doe"}],
        release_date="2026-06-03",
        title="New release",
        doi="10.5281/zenodo.999",
        record_id="999",
    )
    # Appending to existing references preserves the original formatting
    # (e.g., tab-indented fields) byte-for-byte and only adds the new entry
    existing = (
        "@article{smith2020,\n"
        "\tauthor = {Smith, John},\n"
        "\tdoi = {10.1/abc},\n"
        "}\n"
    )
    appended = add_bibtex_entry(existing, new_entry, replace_ids=[])
    # The existing content is preserved byte-for-byte at the start, with a
    # single blank line separating it from the appended entry
    assert appended.startswith(existing)
    assert appended == existing + "\n" + new_entry.strip() + "\n"
    assert appended.count("@misc{Doe2026_999,") == 1
    assert bibtexparser.loads(appended).entries[0]["doi"] == "10.1/abc"
    # Appending to an empty/nonexistent file yields just the new entry
    from_empty = add_bibtex_entry("", new_entry, replace_ids=[])
    assert from_empty.strip().startswith("@misc{Doe2026_999,")
    # A matching entry (by citation key) is replaced, while other entries are
    # left untouched and keep their original formatting
    with_old = existing + (
        "\n@misc{old2021,\n"
        "\tauthor = {Doe, Jane},\n"
        "\ttitle = {Old release},\n"
        "\tdoi = {10.5281/zenodo.999},\n"
        "}\n"
    )
    replaced = add_bibtex_entry(with_old, new_entry, replace_ids=["old2021"])
    assert "Old release" not in replaced
    assert "@article{smith2020,\n\tauthor = {Smith, John}," in replaced
    assert replaced.count("@misc{Doe2026_999,") == 1


def test_add_doi_badge_to_readme():
    badge = "[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.999.svg)](https://doi.org/10.5281/zenodo.999)"  # noqa: E501
    # A README with a title and body gets the badge inserted directly beneath
    # the title with exactly one blank line on either side, and no content is
    # removed or duplicated
    readme = "# My Project\nSome description.\n\n## Section\nDetails here.\n"
    out = add_doi_badge_to_readme(readme, badge=badge, title="My Project")
    assert out.startswith(f"# My Project\n\n{badge}\n\nSome description.")
    assert out.count("# My Project\n") == 1
    assert "Some description." in out
    assert "## Section" in out
    assert "Details here." in out
    # The badge has exactly one blank line above and below it
    lines = out.split("\n")
    idx = lines.index(badge)
    assert lines[idx - 1] == ""
    assert lines[idx - 2] == "# My Project"
    assert lines[idx + 1] == ""
    assert lines[idx + 2].strip()
    # A title-only README does not duplicate the title
    title_only = add_doi_badge_to_readme(
        "# My Project\n", badge=badge, title="My Project"
    )
    assert title_only == f"# My Project\n\n{badge}"
    # An empty/missing README falls back to the provided project title
    from_empty = add_doi_badge_to_readme("", badge=badge, title="My Project")
    assert from_empty == f"# My Project\n\n{badge}"
    # An existing DOI badge is replaced, not duplicated, and sibling badges are
    # preserved in place
    other_badge = "[![CI](https://example.com/ci.svg)](https://example.com)"
    old_badge = "[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.111.svg)](https://doi.org/10.5281/zenodo.111)"  # noqa: E501
    with_old = f"# My Project\n{other_badge}\n\n{old_badge}\n\nBody.\n"
    refreshed = add_doi_badge_to_readme(
        with_old, badge=badge, title="My Project"
    )
    assert refreshed.count("[![DOI](") == 1
    assert badge in refreshed
    assert "zenodo.111" not in refreshed
    assert other_badge in refreshed
    assert "Body." in refreshed


def test_read_authors_from_cff(tmp_dir):
    # No file present yields an empty list
    assert read_authors_from_cff() == []
    cff = {
        "cff-version": "1.2.0",
        "title": "My project",
        "authors": [
            {
                "family-names": "Smith",
                "given-names": "Alice",
                "orcid": "https://orcid.org/0000-0001-2345-6789",
                "affiliation": "SomeU",
            },
            {"family-names": "Jones", "given-names": "Bob"},
            # An entity author without a family name should be skipped
            {"name": "The Research Software Project"},
        ],
    }
    with open("CITATION.cff", "w") as f:
        calkit.ryaml.dump(cff, f)
    authors = read_authors_from_cff()
    assert authors == [
        {
            "first_name": "Alice",
            "last_name": "Smith",
            "affiliation": "SomeU",
            # The full ORCID URL should be normalized to the bare identifier
            "orcid": "0000-0001-2345-6789",
        },
        {"first_name": "Bob", "last_name": "Jones"},
    ]
    # A round trip through create_citation_cff should be readable again
    ck_info = {"title": "My project", "authors": authors, "releases": {}}
    generated = create_citation_cff(
        ck_info=ck_info, release_name="v1", release_date="2026-01-01"
    )
    with open("CITATION.cff", "w") as f:
        calkit.ryaml.dump(generated, f)
    round_tripped = read_authors_from_cff()
    assert round_tripped[0]["first_name"] == "Alice"
    assert round_tripped[0]["last_name"] == "Smith"
    assert round_tripped[0]["orcid"] == "0000-0001-2345-6789"


def test_citation_cff_authors_round_trip(tmp_dir):
    # set_cff_authors writes a CITATION.cff from Calkit-format authors,
    # normalizing ORCIDs to full URLs and keeping affiliations
    set_cff_authors(
        [
            {
                "first_name": "Alice",
                "last_name": "Smith",
                "affiliation": "SomeU",
                "orcid": "0000-0001-2345-6789",
            },
            {"first_name": "Bob", "last_name": "Jones"},
        ],
        ck_info={"title": "My project"},
    )
    cff = calkit.ryaml.load(open("CITATION.cff"))
    assert cff["title"] == "My project"
    assert cff["authors"][0]["orcid"] == (
        "https://orcid.org/0000-0001-2345-6789"
    )
    assert cff["authors"][0]["affiliation"] == "SomeU"
    assert "affiliation" not in cff["authors"][1]
    # The authors are readable back as Calkit author dicts
    assert read_authors_from_cff() == [
        {
            "first_name": "Alice",
            "last_name": "Smith",
            "affiliation": "SomeU",
            "orcid": "0000-0001-2345-6789",
        },
        {"first_name": "Bob", "last_name": "Jones"},
    ]
    # create_citation_cff preserves the existing authors (the source of
    # truth) and ignores the provided fallback list, while refreshing the
    # version/date and adding DOIs from project releases
    ck_info = {
        "title": "My project",
        "releases": {
            "v1": {"kind": "project", "doi": "10.5281/zenodo.1"},
            "fig": {"kind": "figure", "doi": "10.5281/zenodo.2"},
        },
    }
    content = create_citation_cff(
        ck_info=ck_info,
        release_name="v2",
        release_date="2026-02-02",
        authors=[{"first_name": "Z", "last_name": "Ignored"}],
    )
    assert content["version"] == "v2"
    assert content["date-released"] == "2026-02-02"
    assert [a["family-names"] for a in content["authors"]] == [
        "Smith",
        "Jones",
    ]
    # Only project-release DOIs are included as identifiers
    doi_values = [i["value"] for i in content["identifiers"]]
    assert doi_values == ["10.5281/zenodo.1"]
    # With no existing CITATION.cff, the provided author list is used
    os.remove("CITATION.cff")
    content = create_citation_cff(
        ck_info={"title": "T", "releases": {}},
        release_name="v1",
        release_date="2026-01-01",
        authors=[{"first_name": "Carol", "last_name": "Lee"}],
    )
    assert content["authors"] == [
        {"family-names": "Lee", "given-names": "Carol"}
    ]


def test_zip_paths(tmp_dir):
    os.makedirs("data/sub", exist_ok=True)
    with open("data/sub/file.txt", "w") as f:
        f.write("hello")
    with open("root.txt", "w") as f:
        f.write("root")
    zip_path = "archive.zip"
    zip_paths(zip_path, ["data", "root.txt"])
    with zipfile.ZipFile(zip_path) as zipf:
        names = set(zipf.namelist())
        assert "data/sub/file.txt" in names
        assert "root.txt" in names
        assert zipf.getinfo("root.txt").compress_type == zipfile.ZIP_DEFLATED
