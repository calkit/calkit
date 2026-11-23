"""Tests for ``calkit.eol``."""

import os
import subprocess

import calkit
import calkit.eol
from calkit.reproducibility import check_reproducibility


def _git(*args: str, cwd: str = ".") -> str:
    return subprocess.check_output(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            *args,
        ],
        cwd=cwd,
        text=True,
    )


def _make_project() -> None:
    """A repo whose pipeline hashes LF text files, some pinned, plus a
    binary and an untracked output."""
    _git("init", "-q")
    os.makedirs("src")
    with open("src/a.py", "w", newline="\n") as f:
        f.write("x = 1\n")
    with open("pinned.txt", "w", newline="\n") as f:
        f.write("pinned\n")
    with open("out.txt", "w", newline="\n") as f:
        f.write("out\n")
    with open("data.bin", "wb") as f:
        f.write(b"\0\1\n\2")
    with open(".gitattributes", "w", newline="\n") as f:
        f.write("pinned.txt eol=lf\n")
    with open("dvc.yaml", "w", newline="\n") as f:
        f.write(
            "stages:\n"
            "  make:\n"
            "    cmd: echo\n"
            "    deps:\n"
            "      - src\n"
            "      - pinned.txt\n"
            "      - data.bin\n"
            "      - ${item}.csv\n"
            "    outs:\n"
            "      - out.txt:\n"
            "          cache: false\n"
            "      - in-dvc.csv\n"
        )
    _git("add", "-A")
    _git("commit", "-qm", "Set up")


def test_check_pipeline(tmp_dir):
    _make_project()
    found = {f.path: f for f in calkit.eol.check_pipeline()}
    # A dependency inside a directory and a Git-tracked output, but not a
    # pinned file, a binary, or what Git doesn't track
    assert sorted(found) == ["out.txt", "src/a.py"]
    assert all(f.at_risk and not f.rewritten for f in found.values())
    res = check_reproducibility()
    assert res.eol_unpinned == ["out.txt", "src/a.py"]
    assert "[-c line-endings]" in res.to_pretty()
    # Pinning everything leaves nothing to report
    with open(".gitattributes", "w", newline="\n") as f:
        f.write("* text=auto eol=lf\n")
    assert calkit.eol.check_pipeline() == []
    assert check_reproducibility().eol_unpinned == []


def test_check_pipeline_rewritten(tmp_dir):
    """A checkout with ``core.autocrlf``, as on Windows, has CRLF where
    Git has LF."""
    os.makedirs("origin")
    os.chdir("origin")
    _make_project()
    os.chdir("..")
    _git("-c", "core.autocrlf=true", "clone", "-q", "origin", "clone")
    os.chdir("clone")
    _git("config", "core.autocrlf", "true")
    found = {f.path: f for f in calkit.eol.check_pipeline()}
    assert sorted(found) == ["out.txt", "src/a.py"]
    assert all(f.rewritten and not f.pinned for f in found.values())
    # Pinned now, but this checkout is still behind until it's redone
    with open(".gitattributes", "w", newline="\n") as f:
        f.write("* text=auto eol=lf\n")
    found = {f.path: f for f in calkit.eol.check_pipeline()}
    assert all(f.rewritten and f.pinned for f in found.values())
    for path in found:
        os.remove(path)
    _git("checkout", "--", *found)
    assert calkit.eol.check_pipeline() == []


def test_list_tracked_eol_outside_git(tmp_dir):
    assert calkit.eol.list_tracked_eol(["anything"]) == []


def test_run_warns_for_rewritten(tmp_dir):
    """`calkit run` says so when this checkout's line endings make stages
    look out of date, and stays quiet otherwise."""
    os.makedirs("origin")
    os.chdir("origin")
    subprocess.check_call(["calkit", "init"])
    with open("in.txt", "w", newline="\n") as f:
        f.write("in\n")
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "copy": {
                "kind": "shell-command",
                "environment": "_system",
                "command": "cat in.txt > out.txt",
                "inputs": ["in.txt"],
                "outputs": [{"path": "out.txt", "storage": "git"}],
            }
        }
    }
    calkit.save_calkit_info(ck_info)
    result = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "line endings" not in result.stdout + result.stderr
    _git("add", "-A")
    _git("commit", "-qm", "Run")
    os.chdir("..")
    _git("-c", "core.autocrlf=true", "clone", "-q", "origin", "clone")
    os.chdir("clone")
    _git("config", "core.autocrlf", "true")
    result = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    out = result.stdout + result.stderr
    assert "have CRLF line endings here but LF in Git" in out
    assert "* text=auto eol=lf" in out
