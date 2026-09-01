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


def test_source_from_ssh_clone_urls():
    # A clone URL is the most natural thing to paste, so it's recognized as
    # the Git source it is. Before, 'git@github.com:o/r/a.sh' fell through
    # to the Calkit-project reading and was sent to the hub as a project
    # named 'git@github.com:o/r'.
    from calkit.provenance import source_from_location

    assert source_from_location("git@github.com:sup/lol/my-thing") == {
        "git": {
            "repo_url": "git@github.com:sup/lol.git",
            "path": "my-thing",
        }
    }
    # A '.git' suffix is the same repo, and a ref is attached when given
    assert source_from_location(
        "git@github.com:sup/lol.git", ref="branch"
    ) == {"git": {"repo_url": "git@github.com:sup/lol.git", "ref": "branch"}}
    assert source_from_location("ssh://git@github.com/sup/lol/a/b.sh") == {
        "git": {
            "repo_url": "ssh://git@github.com/sup/lol.git",
            "path": "a/b.sh",
        }
    }
    assert source_from_location("git://example.com/sup/lol/a.sh") == {
        "git": {"repo_url": "git://example.com/sup/lol.git", "path": "a.sh"}
    }
    # A Calkit project path is still one, not a host with a colon missing
    assert source_from_location("someone/some-project/scripts/x.sh") == {
        "project": "someone/some-project",
        "path": "scripts/x.sh",
    }
    # A relative path that happens to contain a colon isn't a clone URL:
    # the host has to look like one
    with pytest.raises(ValueError, match="Cannot tell where"):
        source_from_location("notes:todo")


def test_zenodo_record_urls_are_read_as_dois():
    # A link to a Zenodo record is that record, not a file. Reading it as a
    # plain URL would download the landing page and save the HTML as the
    # data, which is the mistake the DOI handling exists to prevent -- so
    # both spellings of the same record have to reach it.
    from calkit.provenance import source_from_location

    doi = {"doi": "10.5281/zenodo.18038227"}
    for url in [
        "https://zenodo.org/records/18038227",
        "https://zenodo.org/record/18038227",
        "http://zenodo.org/records/18038227",
        "https://www.zenodo.org/records/18038227",
        "https://zenodo.org/records/18038227/files/data.csv",
    ]:
        assert source_from_location(url) == doi, url
    # Written as a DOI it already worked, and still does
    assert source_from_location("https://doi.org/10.5281/zenodo.18038227") == (
        doi
    )
    # Anything else on the host is still just a URL
    assert source_from_location("https://zenodo.org/communities/x") == {
        "url": "https://zenodo.org/communities/x"
    }


def test_fetch_rejects_doi():
    from calkit.provenance import fetch

    with pytest.raises(ValueError, match="calkit import zenodo"):
        fetch({"doi": "10.5281/zenodo.1"}, dest_path="x")


def test_git_source_records_intent_not_resolved_state():
    # calkit.yaml says what to follow, which a person writes. Where
    # following it led -- the commit, the checksum -- goes in
    # .calkit/imports.json, so 'ref' is the only revision written here.
    # Pinning is writing a commit hash as the ref: a thing to follow that
    # happens never to move.
    from pydantic import ValidationError

    from calkit.models.core import MiscArtifact

    def source(**git):
        return MiscArtifact(
            path="scripts/setup.sh", imported_from={"git": git}
        ).model_dump(exclude_none=True)["imported_from"]["git"]

    sha = "0123456789abcdef0123456789abcdef01234567"
    intent = {"repo_url": "https://github.com/o/r.git", "path": "a.sh"}
    assert source(**intent, ref="main") == intent | {"ref": "main"}
    # Pinning, with no 'rev' anywhere in calkit.yaml
    assert source(**intent, ref=sha) == intent | {"ref": sha}
    # No ref at all means the repo's default branch
    assert source(**intent) == intent
    # 'rev' is still read for entries written before the split, and still
    # has to be a commit hash rather than something that moves
    assert source(**intent, rev=sha)["rev"] == sha
    with pytest.raises(ValidationError, match="goes in 'ref'"):
        source(**intent, rev="main")


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
    out, lock = fetch(source, dest_path="a.sh")
    assert out["git"]["ref"] == "feature/foo"
    assert out["git"]["path"] == "scripts/a.sh"
    # What it resolved to comes back separately, for the lock file
    assert lock["rev"] and lock["hash"].startswith("sha256:")
    with open("a.sh") as f:
        assert f.read() == "on-feature\n"
    # A ref that resolves as recorded is never widened, even when a longer
    # one would also resolve
    single = source_from_location("https://github.com/o/r/blob/main/a.sh")
    single["git"]["repo_url"] = src
    single["git"]["path"] = "scripts/a.sh"
    out, _ = fetch(single, dest_path="b.sh")
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
    from calkit.provenance import get_importable_artifact_kinds

    hints = get_type_hints(import_path, include_extras=True)
    help_txt = next(
        meta.help for meta in get_args(hints["kind"]) if hasattr(meta, "help")
    )
    for kind in get_importable_artifact_kinds():
        assert f"'{kind}'" in help_txt, kind


def test_import_record_refuses_what_it_cannot_record():
    # These entries exist to be trusted, so a key the schema doesn't know
    # is refused rather than dropped. An untagged union that ignores extras
    # would let a misspelling, a key at the wrong level, or two sources at
    # once all validate while saying less than whoever wrote them meant.
    from pydantic import TypeAdapter, ValidationError

    from calkit.models.core import ImportedFromType

    ta = TypeAdapter(ImportedFromType)
    sha = "0123456789abcdef0123456789abcdef01234567"
    for bad in [
        # 'rev' belongs inside 'git', not beside it
        {"git": {"repo_url": "u", "path": "a", "rev": sha}, "rev": sha},
        # A misspelled field name
        {"url": "https://x/a.csv", "dat": "2026-01-01"},
        # Two sources at once: one of them would have been dropped
        {"url": "https://x/a.csv", "doi": "10.5281/zenodo.1"},
        {"project": "o/p", "path": "a.csv", "url": "https://x/a.csv"},
    ]:
        with pytest.raises(ValidationError):
            ta.validate_python(bad)
    # Each source on its own still validates, with its optional date
    for good in [
        {
            "git": {"repo_url": "u", "path": "a", "rev": sha},
            "date": "2026-01-01",
        },
        {"url": "https://x/a.csv", "date": "2026-01-01"},
        {"doi": "10.5281/zenodo.1"},
        {"project": "o/p", "path": "a.csv", "git_rev": "abc1234"},
    ]:
        assert ta.validate_python(good) is not None


def test_import_lock_store(tmp_dir):
    # The lock is keyed by path, sorted so diffs read as one import
    # changing, and tolerant of the list an older version wrote here
    import json
    import os

    from calkit.provenance import (
        IMPORT_LOCK_FPATH,
        hash_path,
        local_edit,
        read_import_locks,
        write_import_lock,
    )

    assert read_import_locks() == {}
    write_import_lock("b.txt", {"rev": "abc1234"})
    write_import_lock("a.txt", {"rev": "def5678"})
    assert list(read_import_locks()) == ["a.txt", "b.txt"]
    # Dropping one leaves the rest
    write_import_lock("b.txt", None)
    assert list(read_import_locks()) == ["a.txt"]
    # An older version appended a list of Zenodo events here; it is read as
    # absent rather than crashing, since nothing ever consumed it
    with open(IMPORT_LOCK_FPATH, "w") as f:
        json.dump([{"from": "zenodo"}], f)
    assert read_import_locks() == {}
    # A checksum tells an edited file from an untouched one, and says
    # nothing when there is nothing to compare against
    with open("f.txt", "w") as f:
        f.write("one\n")
    lock = {"hash": hash_path("f.txt")}
    assert not local_edit("f.txt", lock)
    with open("f.txt", "a") as f:
        f.write("edited\n")
    assert local_edit("f.txt", lock)
    assert not local_edit("f.txt", None)
    assert not local_edit("f.txt", {"rev": "abc1234"})
    # A hash written by a version using a different algorithm is not
    # mistaken for an edited file; it just can't be compared
    assert not local_edit("f.txt", {"hash": "blake3:" + "0" * 64})
    assert not local_edit("missing.txt", lock)
    # A directory is hashed over its entries and their contents, so a
    # refresh can tell that one was edited before replacing it wholesale
    os.makedirs(os.path.join("d", "sub"), exist_ok=True)
    with open(os.path.join("d", "sub", "x.txt"), "w") as f:
        f.write("one\n")
    before = hash_path("d")
    assert before is not None
    with open(os.path.join("d", "sub", "x.txt"), "a") as f:
        f.write("edited\n")
    assert hash_path("d") != before
    dir_lock = {"hash": before}
    assert local_edit("d", dir_lock)
    # A renamed file is a change too, even with identical content
    os.rename(os.path.join("d", "sub", "x.txt"), os.path.join("d", "sub", "y"))
    assert hash_path("d") != before
    assert hash_path("nowhere-at-all") is None
    # 'fetched' says when this version arrived, not when it was last
    # checked for, so re-recording the same state leaves the file alone --
    # otherwise every refresh would be a commit
    write_import_lock("c.txt", {"rev": "abc1234", "fetched": "2026-01-01"})
    write_import_lock("c.txt", {"rev": "abc1234", "fetched": "2026-06-30"})
    assert read_import_locks()["c.txt"]["fetched"] == "2026-01-01"
    # A different revision is a new version, so the time moves
    write_import_lock("c.txt", {"rev": "def5678", "fetched": "2026-06-30"})
    assert read_import_locks()["c.txt"]["fetched"] == "2026-06-30"


def test_import_paths_must_stay_in_the_project(tmp_dir):
    # An import writes to its path and then hands it to 'git add', so one
    # pointing out of the project would clobber a file elsewhere and then
    # fail confusingly. Checked before anything is fetched or written.
    import os
    import subprocess

    import calkit
    from calkit.provenance import check_project_path

    assert check_project_path("scripts/setup.sh") == ""
    assert check_project_path("a/../b.txt") == ""
    for bad in ["../escape.txt", "/etc/hosts", "a/../../escape.txt"]:
        assert check_project_path(bad), bad
    subprocess.run(["calkit", "init"], check=True, capture_output=True)
    ck_info = calkit.load_calkit_info()
    ck_info["misc"] = [
        {"path": "../escape.txt", "imported_from": {"url": "https://x/a"}}
    ]
    calkit.save_calkit_info(ck_info)
    res = subprocess.run(
        ["calkit", "sync", "import", "../escape.txt"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "points outside the project" in res.stdout + res.stderr
    assert not os.path.exists(os.path.join("..", "escape.txt"))


def test_update_all_with_nothing_refreshable(tmp_dir):
    # Every target skipped means nothing to record or commit, and a
    # project whose only import is a DOI has no lock file to stage --
    # staging one anyway used to raise a git pathspec error before these
    # diagnostics could print
    import os
    import subprocess

    import calkit

    subprocess.run(["calkit", "init"], check=True, capture_output=True)
    ck_info = calkit.load_calkit_info()
    ck_info["misc"] = [
        {"path": "r.txt", "imported_from": {"doi": "10.5281/zenodo.1"}}
    ]
    calkit.save_calkit_info(ck_info)
    res = subprocess.run(
        ["calkit", "sync", "import", "--all"],
        capture_output=True,
        text=True,
    )
    combined = res.stdout + res.stderr
    assert res.returncode != 0
    assert "Skipped r.txt" in combined
    assert "Nothing refreshed; 1 skipped" in combined
    assert "pathspec" not in combined
    # A lock file that isn't JSON is reported rather than read as empty,
    # which would discard every other import's state on the next write
    os.makedirs(".calkit", exist_ok=True)
    with open(os.path.join(".calkit", "imports.json"), "w") as f:
        f.write("{ not json")
    res = subprocess.run(
        ["calkit", "sync", "import", "--all"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "not valid JSON" in res.stdout + res.stderr
