"""Tests for ``cli.show``."""

import os
import subprocess
import sys

import pytest

import calkit


@pytest.mark.skipif(
    sys.platform == "win32", reason="Stands in for the editor with a script"
)
def test_show_latex_diff(tmp_dir, tmp_path_factory):
    stubs = tmp_path_factory.mktemp("stubs")
    opened = stubs / "opened.txt"
    with open(stubs / "code", "w") as f:
        f.write(f'#!/usr/bin/env bash\necho "$@" > {opened}\n')
    os.chmod(stubs / "code", 0o755)
    # As VS Code's integrated terminal sets it, so the editor is used rather
    # than the system's viewer
    env = os.environ | {
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "TERM_PROGRAM": "vscode",
    }

    def show(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["calkit", "show", "latex-diff", *args],
            capture_output=True,
            text=True,
            env=env,
        )

    subprocess.check_call(["git", "init", "-q", "-b", "main", "."])
    subprocess.check_call(["calkit", "dvc", "init", "-q"])
    os.makedirs("paper")
    with open("paper/main.tex", "w") as f:
        f.write("Hello\n")
    ck_info = {
        "environments": {"tex": {"kind": "docker", "image": "texlive"}},
        "pipeline": {
            "stages": {
                "paper": {
                    "kind": "latex",
                    "environment": "tex",
                    "target_path": "paper/main.tex",
                    "diffs": ["v1", ["v1", "v2"]],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["git", "add", "-A"])
    subprocess.check_call(
        [
            "git",
            "-c",
            "user.email=t@e.com",
            "-c",
            "user.name=T",
            "commit",
            "-qm",
            "first",
        ]
    )
    # Which diff has to be clear
    result = show()
    assert result.returncode != 0
    assert "More than one diff matches" in result.stderr
    result = show("paper/main.pdf")
    assert "More than one diff matches" in result.stderr
    result = show("nope")
    assert "No LaTeX diff matches 'nope'" in result.stderr
    # One that isn't built says how to build it
    result = show("paper-diff-v1")
    assert result.returncode != 0
    assert "calkit run paper-diff-v1" in result.stderr
    assert not opened.exists()
    # A built one opens in the editor
    os.makedirs(".calkit/env-locks/tex")
    with open(".calkit/env-locks/tex/arm64.json", "w") as f:
        f.write("{}\n")
    out = ".calkit/latex-diffs/v1/paper/main.pdf"
    os.makedirs(os.path.dirname(out))
    with open(out, "w") as f:
        f.write("diff\n")
    subprocess.check_call(["calkit", "dvc", "commit", "-qf", "paper-diff-v1"])
    result = show("paper-diff-v1")
    assert result.returncode == 0, result.stderr
    assert opened.read_text().strip() == out
    assert "stale" not in result.stdout
    # A stale one still opens, with a warning, so it can be read while it's
    # rebuilt
    opened.unlink()
    with open("paper/main.tex", "a") as f:
        f.write("More\n")
    result = show(out)
    assert result.returncode == 0, result.stderr
    assert "is stale" in result.stdout
    assert opened.read_text().strip() == out
