"""Tests for ``calkit.cli.import_``."""

import subprocess

import pytest


@pytest.mark.skip(reason="Automated requests to Zenodo can be flaky")
def test_import_zenodo(tmp_dir, monkeypatch):
    subprocess.run(["calkit", "init"], check=True)
    # Temporarily disable dev mode so we can download a real record
    monkeypatch.setenv("CALKIT_USE_PROD_FOR_TESTS", "1")
    subprocess.run(
        [
            "calkit",
            "import",
            "zenodo",
            "https://doi.org/10.5281/zenodo.18038227",
            "data/imported",
            "--kind",
            "dataset",
        ],
        check=True,
    )
    # TODO: Test more about this


def test_import_and_update_a_path(tmp_dir):
    # Covers importing a file from a Git repo, refreshing it along its
    # 'ref' or the default branch, and the ways that can go wrong
    import json
    import os

    import git as gitpy

    import calkit

    def locked(path):
        # What the fetch resolved to lives in .calkit/imports.json, not in
        # calkit.yaml, which carries only what a person declared
        return calkit.provenance.read_import_locks()[path]

    def commit(repo, message):
        repo.git.add("-A")
        repo.index.commit(
            message,
            author=gitpy.Actor("Tester", "t@example.com"),
            committer=gitpy.Actor("Tester", "t@example.com"),
        )
        return repo.head.commit.hexsha

    # A repo that isn't a Calkit project, standing in for a shared setups
    # repo kept alongside several projects
    src = os.path.abspath("src-repo")
    os.makedirs(os.path.join(src, "setups"))
    src_repo = gitpy.Repo.init(src, initial_branch="main")
    with open(os.path.join(src, "setups", "setup.sh"), "w") as f:
        f.write("export FOO=1\n")
    first_rev = commit(src_repo, "init")
    subprocess.run(["calkit", "init"], check=True)
    subprocess.run(
        [
            "calkit",
            "import",
            "path",
            "setups/setup.sh",
            "scripts/setup.sh",
            "--git-repo",
            src,
            "--git-ref",
            "main",
        ],
        check=True,
    )
    with open("scripts/setup.sh") as f:
        assert f.read() == "export FOO=1\n"
    entries = calkit.load_calkit_info()["misc"]
    assert len(entries) == 1
    source = entries[0]["imported_from"]["git"]
    # A branch was named, so that is what calkit.yaml records -- the
    # commit it resolved to goes in the lock file
    assert "rev" not in source
    assert source["ref"] == "main"
    assert source["path"] == "setups/setup.sh"
    assert locked("scripts/setup.sh")["rev"] == first_rev
    assert locked("scripts/setup.sh")["hash"].startswith("sha256:")
    # Importing over it again needs saying so
    res = subprocess.run(
        [
            "calkit",
            "import",
            "path",
            "setups/setup.sh",
            "scripts/setup.sh",
            "--git-repo",
            src,
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "already exists" in res.stdout + res.stderr
    # So does importing over a file nothing records
    with open("unrecorded.sh", "w") as f:
        f.write("mine\n")
    res = subprocess.run(
        [
            "calkit",
            "import",
            "path",
            "setups/setup.sh",
            "unrecorded.sh",
            "--git-repo",
            src,
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "already exists" in res.stdout + res.stderr
    with open("unrecorded.sh") as f:
        assert f.read() == "mine\n"
    # The source moves on, and the local copy is edited. Refreshing would
    # discard that edit, so it is refused until asked for twice -- the
    # checksum in the lock file is what makes the edit visible.
    with open(os.path.join(src, "setups", "setup.sh"), "w") as f:
        f.write("export FOO=2\n")
    second_rev = commit(src_repo, "update")
    with open("scripts/setup.sh", "a") as f:
        f.write("# local edit\n")
    res = subprocess.run(
        ["calkit", "update", "import", "scripts/setup.sh"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "has been edited since it was imported" in res.stdout + res.stderr
    with open("scripts/setup.sh") as f:
        assert "# local edit" in f.read()
    # Asked for explicitly, the source wins
    subprocess.run(
        ["calkit", "update", "import", "scripts/setup.sh", "--force"],
        check=True,
    )
    with open("scripts/setup.sh") as f:
        assert f.read() == "export FOO=2\n"
    assert locked("scripts/setup.sh")["rev"] == second_rev
    # With no 'ref' recorded, refreshing takes the latest on the default
    # branch rather than re-reading the commit it last landed on
    ck_info = calkit.load_calkit_info()
    del ck_info["misc"][0]["imported_from"]["git"]["ref"]
    calkit.save_calkit_info(ck_info)
    with open(os.path.join(src, "setups", "setup.sh"), "w") as f:
        f.write("export FOO=3\n")
    third_rev = commit(src_repo, "third")
    subprocess.run(
        ["calkit", "update", "import", "scripts/setup.sh", "--no-commit"],
        check=True,
    )
    with open("scripts/setup.sh") as f:
        assert f.read() == "export FOO=3\n"
    assert locked("scripts/setup.sh")["rev"] == third_rev
    # --git-ref changes what the entry follows, from now on rather than
    # just this once, so a later refresh stays on the tag
    src_repo.create_tag("v1", ref=second_rev)
    subprocess.run(
        [
            "calkit",
            "update",
            "import",
            "scripts/setup.sh",
            "--git-ref",
            "v1",
            "--no-commit",
        ],
        check=True,
    )
    with open("scripts/setup.sh") as f:
        assert f.read() == "export FOO=2\n"
    source = calkit.load_calkit_info()["misc"][0]["imported_from"]["git"]
    assert source["ref"] == "v1"
    assert locked("scripts/setup.sh")["rev"] == second_rev
    subprocess.run(
        ["calkit", "update", "import", "scripts/setup.sh", "--no-commit"],
        check=True,
    )
    with open("scripts/setup.sh") as f:
        assert f.read() == "export FOO=2\n"
    # Both commands touch only the file and calkit.yaml. Unrelated staged
    # work must not be swept into a commit claiming to be about the import,
    # and an unchanged file must not be called updated just because
    # something else happened to be staged.
    repo = calkit.git.get_repo()
    # Settle what the '--no-commit' refreshes above left staged, so the
    # only thing outstanding is the unrelated file
    repo.git.add("-A")
    repo.index.commit(
        "settle",
        author=gitpy.Actor("Tester", "t@example.com"),
        committer=gitpy.Actor("Tester", "t@example.com"),
    )
    with open("unrelated.txt", "w") as f:
        f.write("mine\n")
    repo.git.add("unrelated.txt")
    res = subprocess.run(
        ["calkit", "update", "import", "scripts/setup.sh"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "already up-to-date" in res.stdout + res.stderr
    assert "unrelated.txt" in repo.git.diff("--cached", "--name-only")
    # And when there is something to commit, the unrelated file stays out
    with open(os.path.join(src, "setups", "setup.sh"), "w") as f:
        f.write("export FOO=4\n")
    commit(src_repo, "fourth")
    subprocess.run(
        [
            "calkit",
            "update",
            "import",
            "scripts/setup.sh",
            "--git-ref",
            "main",
        ],
        check=True,
    )
    committed = repo.git.show("--stat", "--format=", "HEAD")
    assert "scripts/setup.sh" in committed
    assert "unrelated.txt" not in committed
    assert "unrelated.txt" in repo.git.diff("--cached", "--name-only")
    # A source that isn't a Git repo has no ref to follow
    ck_info = calkit.load_calkit_info()
    ck_info["misc"].append(
        {"path": "other.txt", "imported_from": {"url": "https://x.invalid/a"}}
    )
    calkit.save_calkit_info(ck_info)
    res = subprocess.run(
        ["calkit", "update", "import", "other.txt", "--git-ref", "main"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "not imported from a Git repo" in res.stdout + res.stderr
    # --kind chooses which list it lands in, and --overwrite moves an
    # entry out of whichever list it was in
    subprocess.run(
        [
            "calkit",
            "import",
            "path",
            "setups/setup.sh",
            "figures/f.sh",
            "--git-repo",
            src,
            "--kind",
            "figure",
        ],
        check=True,
    )
    ck_info = calkit.load_calkit_info()
    assert [e["path"] for e in ck_info["figures"]] == ["figures/f.sh"]
    assert "scripts/setup.sh" in [e["path"] for e in ck_info["misc"]]
    assert "figures/f.sh" not in [e["path"] for e in ck_info["misc"]]
    subprocess.run(
        [
            "calkit",
            "import",
            "path",
            "setups/setup.sh",
            "figures/f.sh",
            "--git-repo",
            src,
            "--kind",
            "misc",
            "--overwrite",
        ],
        check=True,
    )
    ck_info = calkit.load_calkit_info()
    assert "figures" not in ck_info or not ck_info["figures"]
    assert "figures/f.sh" in [e["path"] for e in ck_info["misc"]]
    # 'calkit list imports' walks every artifact kind, so an import shows
    # up whichever list it was recorded in, with its source described
    listed = subprocess.check_output(["calkit", "list", "imports"], text=True)
    assert "scripts/setup.sh" in listed
    assert "figures/f.sh" in listed
    assert "other.txt" in listed
    assert "https://x.invalid/a" in listed
    # A file that was never imported isn't an import
    assert "unrecorded.sh" not in listed
    as_json = json.loads(
        subprocess.check_output(
            ["calkit", "list", "imports", "--json"], text=True
        )
    )
    assert {e["path"] for e in as_json} == {
        "scripts/setup.sh",
        "figures/f.sh",
        "other.txt",
    }
    assert {e["kind"] for e in as_json} == {"misc"}
    # '--all' refreshes everything imported, whatever list it is in, in
    # one commit. An entry that can't be refreshed in place is reported and
    # skipped rather than stopping the rest, and the command exits non-zero
    # so a script notices.
    with open(os.path.join(src, "setups", "setup.sh"), "w") as f:
        f.write("export FOO=5\n")
    commit(src_repo, "fifth")
    ck_info = calkit.load_calkit_info()
    # Drop the URL entry added earlier, so the only source that can't be
    # reached is the one this block is about
    ck_info["misc"] = [e for e in ck_info["misc"] if e["path"] != "other.txt"]
    ck_info["misc"].append(
        {
            "path": "unreachable.sh",
            "imported_from": {
                "git": {
                    "repo_url": os.path.join(tmp_dir, "no-such-repo"),
                    "path": "a.sh",
                    "rev": "0123abc",
                }
            },
        }
    )
    calkit.save_calkit_info(ck_info)
    res = subprocess.run(
        ["calkit", "update", "import", "--all"],
        capture_output=True,
        text=True,
    )
    combined = res.stdout + res.stderr
    assert res.returncode != 0
    assert "Skipped unreachable.sh" in combined
    # The reachable ones went through anyway
    with open("scripts/setup.sh") as f:
        assert f.read() == "export FOO=5\n"
    head = repo.git.show("--stat", "--format=%s", "HEAD")
    assert "imported objects from their sources" in head
    # The one that couldn't be fetched isn't in the commit
    assert "unreachable.sh" not in head
    ck_info = calkit.load_calkit_info()
    ck_info["misc"] = [
        e for e in ck_info["misc"] if e["path"] != "unreachable.sh"
    ]
    calkit.save_calkit_info(ck_info)
    # A path and --all say different things, and one ref can't mean the
    # same thing in several repos
    for args, msg in [
        (["scripts/setup.sh", "--all"], "not both"),
        (["--all", "--git-ref", "main"], "can't be combined with --all"),
        ([], "or --all to refresh every one"),
    ]:
        res = subprocess.run(
            ["calkit", "update", "import"] + args,
            capture_output=True,
            text=True,
        )
        assert res.returncode != 0
        assert msg in res.stdout + res.stderr, args
    # A kind whose entries can't say where they came from is refused, as
    # is one that isn't a kind at all
    for bad_kind in ["table", "widgets"]:
        res = subprocess.run(
            [
                "calkit",
                "import",
                "path",
                "setups/setup.sh",
                "x.sh",
                "--git-repo",
                src,
                "--kind",
                bad_kind,
            ],
            capture_output=True,
            text=True,
        )
        assert res.returncode != 0
        assert "Invalid --kind" in res.stdout + res.stderr
    # Refreshing something nothing records
    res = subprocess.run(
        ["calkit", "update", "import", "nope.txt"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "Nothing recorded" in res.stdout + res.stderr
