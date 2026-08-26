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


def test_import_and_update_path(tmp_dir):
    # Covers importing a file from a Git repo, refreshing it along its
    # 'ref' or the default branch, and the ways that can go wrong
    import os

    import calkit

    def git(*args, wdir):
        subprocess.run(
            ["git", "-C", wdir, *args],
            check=True,
            capture_output=True,
        )

    def commit(wdir, message):
        git("add", "-A", wdir=wdir)
        git(
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=Tester",
            "commit",
            "-qm",
            message,
            wdir=wdir,
        )
        return subprocess.check_output(
            ["git", "-C", wdir, "rev-parse", "HEAD"], text=True
        ).strip()

    # A repo that isn't a Calkit project, standing in for a shared setups
    # repo kept alongside several projects
    src = os.path.abspath("src-repo")
    os.makedirs(os.path.join(src, "setups"))
    git("init", "-q", "-b", "main", ".", wdir=src)
    with open(os.path.join(src, "setups", "setup.sh"), "w") as f:
        f.write("export FOO=1\n")
    first_rev = commit(src, "init")
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
    # A branch was named, but what gets recorded is the commit it resolved
    # to, so the entry says which bytes are here
    assert source["rev"] == first_rev
    assert source["ref"] == "main"
    assert source["path"] == "setups/setup.sh"
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
    # The source moves on, and a local edit is made that must not survive
    with open(os.path.join(src, "setups", "setup.sh"), "w") as f:
        f.write("export FOO=2\n")
    second_rev = commit(src, "update")
    with open("scripts/setup.sh", "a") as f:
        f.write("# local edit\n")
    subprocess.run(
        ["calkit", "update", "path", "scripts/setup.sh"], check=True
    )
    with open("scripts/setup.sh") as f:
        assert f.read() == "export FOO=2\n"
    source = calkit.load_calkit_info()["misc"][0]["imported_from"]["git"]
    assert source["rev"] == second_rev
    # With no 'ref' recorded, refreshing takes the latest on the default
    # branch rather than re-reading the commit it last landed on
    ck_info = calkit.load_calkit_info()
    del ck_info["misc"][0]["imported_from"]["git"]["ref"]
    calkit.save_calkit_info(ck_info)
    with open(os.path.join(src, "setups", "setup.sh"), "w") as f:
        f.write("export FOO=3\n")
    third_rev = commit(src, "third")
    subprocess.run(
        ["calkit", "update", "path", "scripts/setup.sh", "--no-commit"],
        check=True,
    )
    with open("scripts/setup.sh") as f:
        assert f.read() == "export FOO=3\n"
    assert (
        calkit.load_calkit_info()["misc"][0]["imported_from"]["git"]["rev"]
        == third_rev
    )
    # --git-ref changes what the entry follows, from now on rather than
    # just this once, so a later refresh stays on the tag
    git("tag", "v1", second_rev, wdir=src)
    subprocess.run(
        [
            "calkit",
            "update",
            "path",
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
    assert source["rev"] == second_rev
    subprocess.run(
        ["calkit", "update", "path", "scripts/setup.sh", "--no-commit"],
        check=True,
    )
    with open("scripts/setup.sh") as f:
        assert f.read() == "export FOO=2\n"
    # A source that isn't a Git repo has no ref to follow
    ck_info = calkit.load_calkit_info()
    ck_info["misc"].append(
        {"path": "other.txt", "imported_from": {"url": "https://x.invalid/a"}}
    )
    calkit.save_calkit_info(ck_info)
    res = subprocess.run(
        ["calkit", "update", "path", "other.txt", "--git-ref", "main"],
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
            "figures",
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
    # A kind whose entries can't say where they came from is refused, as
    # is one that isn't a kind at all
    for bad_kind in ["tables", "widgets"]:
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
        ["calkit", "update", "path", "nope.txt"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "Nothing recorded" in res.stdout + res.stderr
