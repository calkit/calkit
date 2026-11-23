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
    assert {"out.txt", "src/a.py"} <= set(calkit.eol.convert_worktree())
    assert calkit.eol.check_pipeline() == []
    assert _git("status", "--porcelain") == " M .gitattributes\n"


def test_list_tracked_eol_outside_git(tmp_dir):
    assert calkit.eol.list_tracked_eol(["anything"]) == []


def test_run_warns_for_rewritten(tmp_dir):
    """`calkit run` says so when this checkout's line endings make stages
    look out of date, and stays quiet otherwise."""
    os.makedirs("origin")
    os.chdir("origin")
    subprocess.check_call(["calkit", "init"])
    # As in a project from before init pinned line endings
    os.remove(".gitattributes")
    _git("commit", "-qam", "Unpin")
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
    assert "calkit fix line-endings" in out
    # Which fixes it, without anything left to show as modified
    _git("reset", "-q", "--hard")
    subprocess.check_call(["calkit", "fix", "line-endings"])
    assert _git("status", "--porcelain") == "?? .gitattributes\n"
    result = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "line endings" not in out
    assert _git("status", "--porcelain") == "?? .gitattributes\n"


def test_pin(tmp_dir):
    """Pinning a repo checked out with CRLF, as on Windows, makes no
    committed file read as changed, and leaves the checkout clean."""
    os.makedirs("origin")
    os.chdir("origin")
    _git("init", "-q")
    # So the CRLF file is committed with CRLF, on Windows too
    _git("config", "core.autocrlf", "false")
    with open("lf.txt", "w", newline="\n") as f:
        f.write("a\nb\n")
    with open("crlf.txt", "w", newline="") as f:
        f.write("a\r\nb\r\n")
    with open("run.bat", "w", newline="\n") as f:
        f.write("@echo off\n")
    with open("data.bin", "wb") as f:
        f.write(b"\0\1\r\n\2")
    with open(".gitattributes", "w", newline="\n") as f:
        f.write("*.txt diff\n")
    _git("add", "-A")
    _git("commit", "-qm", "Set up")
    os.chdir("..")
    _git("-c", "core.autocrlf=true", "clone", "-q", "origin", "clone")
    os.chdir("clone")
    _git("config", "core.autocrlf", "true")
    with open("lf.txt", "rb") as f:
        assert f.read() == b"a\r\nb\r\n"
    # An uncommitted change survives
    with open("lf.txt", "ab") as f:
        f.write(b"c\r\n")
    res = calkit.eol.pin()
    assert res.wrote_gitattributes
    # The batch file is CRLF here already
    assert res.converted == ["lf.txt"]
    with open("lf.txt", "rb") as f:
        assert f.read() == b"a\nb\nc\n"
    with open("run.bat", "rb") as f:
        assert f.read() == b"@echo off\r\n"
    with open("crlf.txt", "rb") as f:
        assert f.read() == b"a\r\nb\r\n"
    with open("data.bin", "rb") as f:
        assert f.read() == b"\0\1\r\n\2"
    with open(".gitattributes") as f:
        attrs = f.read()
    # First, so the project's own rules still win
    assert attrs.startswith("# >>> calkit line endings")
    assert attrs.endswith("\n\n*.txt diff\n")
    assert _git("status", "--porcelain") == (" M .gitattributes\n M lf.txt\n")
    assert _git("diff", "--stat", "--", "lf.txt").count("|") == 1
    # Again, nothing to do
    res = calkit.eol.pin()
    assert not res.wrote_gitattributes and res.converted == []
    # On macOS or Linux, the batch file is the one to rewrite
    os.chdir("../origin")
    res = calkit.eol.pin()
    assert res.converted == ["run.bat"]
    with open("run.bat", "rb") as f:
        assert f.read() == b"@echo off\r\n"
    assert _git("status", "--porcelain") == " M .gitattributes\n"


def test_write_rules_respects_existing(tmp_dir):
    with open(".gitattributes", "w", newline="\n") as f:
        f.write("* text=auto eol=lf\n")
    assert calkit.eol.pins_all()
    assert not calkit.eol.write_rules()
    os.remove(".gitattributes")
    assert calkit.eol.write_rules()
    assert calkit.eol.pins_all()
    assert not calkit.eol.write_rules()


def test_init_pins(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    with open(".gitattributes") as f:
        assert "* text=auto eol=lf" in f.read()
    assert ".gitattributes" in _git("show", "--name-only", "--format=")
    assert _git("status", "--porcelain") == ""


def test_submodule(tmp_dir, monkeypatch):
    """A submodule's files are checked, and pinned in this clone, since
    the project's .gitattributes doesn't reach them."""
    os.makedirs("sub")
    os.chdir("sub")
    _git("init", "-q")
    with open("plot.py", "w", newline="\n") as f:
        f.write("x = 1\n")
    _git("add", "-A")
    _git("commit", "-qm", "Sub")
    os.chdir("..")
    os.makedirs("origin")
    os.chdir("origin")
    _git("init", "-q")
    _git(
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        os.path.abspath("../sub"),
        "utils",
    )
    with open("dvc.yaml", "w", newline="\n") as f:
        f.write(
            "stages:\n"
            "  make:\n"
            "    cmd: echo\n"
            "    deps:\n"
            "      - utils/plot.py\n"
            "      - utils\n"
        )
    _git("add", "-A")
    _git("commit", "-qm", "Set up")
    os.chdir("..")
    # As on Windows
    with open("gitconfig", "w") as f:
        f.write("[core]\n\tautocrlf = true\n[protocol]\n\tallow = always\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.path.abspath("gitconfig"))
    _git("clone", "-q", "--recursive", "origin", "clone")
    os.chdir("clone")
    assert calkit.eol.submodules() == ["utils"]
    found = calkit.eol.check_pipeline()
    assert [f.path for f in found] == ["utils/plot.py"]
    assert found[0].rewritten
    res = calkit.eol.pin()
    assert res.submodules == ["utils"]
    assert "utils/plot.py" in res.converted
    with open("utils/plot.py", "rb") as f:
        assert f.read() == b"x = 1\n"
    assert _git("status", "--porcelain", cwd="utils") == ""
    # Still at risk in other clones, but not rewritten in this one
    found = calkit.eol.check_pipeline()
    assert [f.path for f in found] == ["utils/plot.py"]
    assert not found[0].rewritten
    # And a checkout in it now keeps what was committed
    os.remove("utils/plot.py")
    _git("checkout", "--", "plot.py", cwd="utils")
    with open("utils/plot.py", "rb") as f:
        assert f.read() == b"x = 1\n"
