"""Tests for ``calkit.provenance``."""

import pytest


def test_source_from_location():
    # Covers GitHub and GitLab file links with and without a revision,
    # explicit refs, DOIs however written, plain URLs, and Calkit project
    # paths
    from calkit.provenance import default_dest_path, source_from_location

    gh = "https://github.com/someone/repo.git"
    # Written out by hand, with no revision: the default branch is what
    # gets fetched, now and on every refresh
    assert source_from_location(
        "https://github.com/someone/repo/path/to/file"
    ) == {"git": {"repo_url": gh, "path": "path/to/file"}}
    assert source_from_location(
        "https://github.com/someone/repo/blob/main/path/to/file"
    ) == {"git": {"repo_url": gh, "path": "path/to/file", "ref": "main"}}
    # A commit is a thing to follow that happens never to move, so it is
    # recorded the same way, and refreshing the import stays on it
    sha = "0123456789abcdef0123456789abcdef01234567"
    assert source_from_location(
        f"https://github.com/someone/repo/blob/{sha}/a.sh"
    ) == {"git": {"repo_url": gh, "path": "a.sh", "ref": sha}}
    assert source_from_location(
        "https://raw.githubusercontent.com/someone/repo/main/a/b.sh"
    ) == {"git": {"repo_url": gh, "path": "a/b.sh", "ref": "main"}}
    assert source_from_location(
        "https://raw.githubusercontent.com/someone/repo/refs/heads/dev/a.sh"
    ) == {"git": {"repo_url": gh, "path": "a.sh", "ref": "dev"}}
    assert source_from_location(
        "https://gitlab.com/grp/sub/repo/-/blob/v1.2/a/b.sh"
    ) == {
        "git": {
            "repo_url": "https://gitlab.com/grp/sub/repo.git",
            "path": "a/b.sh",
            "ref": "v1.2",
        }
    }
    # An explicit ref wins over whatever the URL said
    assert source_from_location(
        f"https://github.com/someone/repo/blob/{sha}/a.sh", ref="main"
    ) == {"git": {"repo_url": gh, "path": "a.sh", "ref": "main"}}
    # A branch name can contain slashes, and the URL doesn't say where it
    # ends; an explicit ref settles it
    assert source_from_location(
        "https://github.com/someone/repo/blob/feature/foo/scripts/a.sh"
    ) == {
        "git": {"repo_url": gh, "path": "foo/scripts/a.sh", "ref": "feature"}
    }
    assert source_from_location(
        "https://github.com/someone/repo/blob/feature/foo/scripts/a.sh",
        ref="feature/foo",
    ) == {
        "git": {"repo_url": gh, "path": "scripts/a.sh", "ref": "feature/foo"}
    }
    # A browser writes a space as '%20', but the checkout doesn't
    assert source_from_location(
        "https://github.com/someone/repo/blob/main/a%20b.csv"
    ) == {"git": {"repo_url": gh, "path": "a b.csv", "ref": "main"}}
    # A DOI resolves to a landing page, so recognizing it is what stops
    # the HTML from being saved and called the data
    for written in [
        "10.5281/zenodo.18038227",
        "doi:10.5281/zenodo.18038227",
        "https://doi.org/10.5281/zenodo.18038227",
        "https://dx.doi.org/10.5281/zenodo.18038227",
    ]:
        assert source_from_location(written) == {
            "doi": "10.5281/zenodo.18038227"
        }
    # Any other host is just an address to download from
    assert source_from_location("https://example.com/thing.csv") == {
        "url": "https://example.com/thing.csv"
    }
    # A repo's front page names no file, so there is nothing to import
    assert source_from_location("https://github.com/someone/repo") == {
        "url": "https://github.com/someone/repo"
    }
    assert source_from_location("someone/some-project/scripts/setup.sh") == {
        "project": "someone/some-project",
        "path": "scripts/setup.sh",
    }
    with pytest.raises(ValueError, match="Cannot tell where"):
        source_from_location("just-a-name")
    # Where each lands with no destination given
    assert (
        default_dest_path(source_from_location("https://x.org/a/b.csv"))
        == "b.csv"
    )
    assert (
        default_dest_path(
            source_from_location("https://github.com/o/r/blob/main/a/b.sh")
        )
        == "b.sh"
    )
    assert (
        default_dest_path(source_from_location("o/p/scripts/setup.sh"))
        == "scripts/setup.sh"
    )


def test_fetch_rejects_doi():
    from calkit.provenance import fetch

    with pytest.raises(ValueError, match="calkit import zenodo"):
        fetch({"doi": "10.5281/zenodo.1"}, dest_path="x")


def test_hand_authored_git_source():
    # An entry can be written by hand as intent, with no commit invented
    from pydantic import ValidationError

    from calkit.models.core import MiscArtifact

    def source(**git):
        return MiscArtifact(
            path="scripts/setup.sh", imported_from={"git": git}
        ).model_dump(exclude_none=True)["imported_from"]["git"]

    intent = {"repo_url": "https://github.com/o/r.git", "path": "a.sh"}
    # What a person writes: where it comes from and what to follow. The
    # commit is the tool's to fill in, so requiring it here would mean
    # inventing one to be allowed to say the rest.
    assert source(**intent, ref="main") == intent | {"ref": "main"}
    assert source(**intent) == intent
    # A branch in 'rev' is the mistake worth catching, since it would make
    # the entry name something that moves
    with pytest.raises(ValidationError, match="goes in 'ref'"):
        source(**intent, rev="main")
    sha = "0123456789abcdef0123456789abcdef01234567"
    assert source(**intent, rev=sha)["rev"] == sha
    assert source(**intent, rev=sha[:7])["rev"] == sha[:7]


def test_fetch_resolves_a_slashed_ref(tmp_dir):
    # A branch name can contain slashes, and a forge URL doesn't say where
    # the ref ends and the path begins. The split guessed when the URL is
    # read is checked against the repo and corrected, and the corrected one
    # is what gets recorded.
    import os

    import git as gitpy

    from calkit.provenance import fetch, source_from_location

    def commit(repo, message):
        repo.git.add("-A")
        repo.index.commit(
            message,
            author=gitpy.Actor("Tester", "t@example.com"),
            committer=gitpy.Actor("Tester", "t@example.com"),
        )

    src = os.path.abspath("src")
    os.makedirs(os.path.join(src, "scripts"))
    repo = gitpy.Repo.init(src, initial_branch="main")
    with open(os.path.join(src, "scripts", "a.sh"), "w") as f:
        f.write("on-main\n")
    commit(repo, "init")
    repo.git.checkout("-b", "feature/foo")
    with open(os.path.join(src, "scripts", "a.sh"), "w") as f:
        f.write("on-feature\n")
    commit(repo, "feat")
    repo.git.checkout("main")
    # As parsed, the ref is cut at one segment, which is wrong here
    source = source_from_location(
        "https://github.com/o/r/blob/feature/foo/scripts/a.sh"
    )
    assert source["git"]["ref"] == "feature"
    assert source["git"]["path"] == "foo/scripts/a.sh"
    source["git"]["repo_url"] = src
    out = fetch(source, dest_path="a.sh")
    assert out["git"]["ref"] == "feature/foo"
    assert out["git"]["path"] == "scripts/a.sh"
    with open("a.sh") as f:
        assert f.read() == "on-feature\n"
    # A ref that resolves as recorded is never widened, even when a longer
    # one would also resolve
    single = source_from_location("https://github.com/o/r/blob/main/a.sh")
    single["git"]["repo_url"] = src
    single["git"]["path"] = "scripts/a.sh"
    out = fetch(single, dest_path="b.sh")
    assert out["git"]["ref"] == "main"
    with open("b.sh") as f:
        assert f.read() == "on-main\n"


def test_importable_artifact_types_come_from_the_models():
    # Whether a kind can record an import is a fact about its model, so it
    # is read off them rather than listed by hand
    from typing import get_args

    from pydantic import BaseModel

    from calkit.models.core import ProjectInfo
    from calkit.provenance import (
        PROVENANCE_ARTIFACT_TYPES,
        get_importable_artifact_types,
    )

    importable = get_importable_artifact_types()
    assert set(importable) <= set(PROVENANCE_ARTIFACT_TYPES)
    # Every kind that is offered can actually record an import, and every
    # kind that can is offered, so the two can't drift apart. Tables and
    # presentations don't take 'imported_from' yet; adding it to one should
    # be all it takes to make it importable.
    for kind in PROVENANCE_ARTIFACT_TYPES:
        models = [
            arg
            for arg in get_args(ProjectInfo.model_fields[kind].annotation)
            for arg in (arg, *get_args(arg))
            if isinstance(arg, type) and issubclass(arg, BaseModel)
        ]
        assert models, kind
        takes_import = any("imported_from" in m.model_fields for m in models)
        assert (kind in importable) == takes_import, kind
    assert "datasets" in importable
    assert "tables" not in importable


def test_import_path_kind_help_lists_what_it_accepts():
    # The help text spells the kinds out, which is worth having and is a
    # second place they're written down. Held to the derived list so a kind
    # gaining 'imported_from' can't leave the help behind.
    from typing import get_args, get_type_hints

    from calkit.cli.import_ import import_path
    from calkit.provenance import get_importable_artifact_types

    hints = get_type_hints(import_path, include_extras=True)
    help_txt = next(
        meta.help for meta in get_args(hints["kind"]) if hasattr(meta, "help")
    )
    for kind in get_importable_artifact_types():
        assert f"'{kind}'" in help_txt, kind
