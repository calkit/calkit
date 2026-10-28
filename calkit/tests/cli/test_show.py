"""Tests for ``cli.show``."""

import json
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


def _project_with_a_result_and_a_table():
    import git

    repo = git.Repo.init()
    os.makedirs("results", exist_ok=True)
    with open("results/kernels.csv", "w") as f:
        f.write(
            "kernel,registers_baseline,registers_mod,U [m/s]\n"
            "microphysics,255,153,[b]1\ncloud_fraction,38,38,[/x]\n"
        )
    with open("results/summary.json", "w") as f:
        f.write('{"speedup_pct": 5.35, "device": {"change_pct": -6.25}}')
    ck_info = {
        "pipeline": {
            "stages": {
                "export": {
                    "kind": "shell-command",
                    "command": "echo hi",
                    "outputs": ["results/kernels.csv"],
                }
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo.git.add(all=True)
    repo.git.commit("-m", "Add a result and a table")
    return repo


def test_show_table(tmp_dir):
    _project_with_a_result_and_a_table()
    out = subprocess.check_output(
        ["calkit", "show", "table", "results/kernels.csv"], text=True
    )
    assert "registers_baseline" in out
    assert "microphysics" in out
    # Brackets, e.g., units, are shown as written rather than as markup
    assert "U [m/s]" in out
    assert "[b]1" in out
    assert "[/x]" in out
    # Columns can be globbed and rows filtered, and the footer says what
    # was left out
    out = subprocess.check_output(
        [
            "calkit",
            "show",
            "table",
            "results/kernels.csv",
            "-c",
            "kernel,*_mod",
            "-f",
            "registers_baseline>100",
        ],
        text=True,
    )
    assert "registers_baseline" not in out
    assert "cloud_fraction" not in out
    assert "1 of 2 rows" in out
    # A column that isn't there names the ones that are
    result = subprocess.run(
        ["calkit", "show", "table", "results/kernels.csv", "-c", "regs"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "registers_baseline" in result.stdout + result.stderr
    # At a Git ref the committed version is read, not the working tree
    with open("results/kernels.csv", "a") as f:
        f.write("new_kernel,1,1\n")
    out = subprocess.check_output(
        [
            "calkit",
            "show",
            "table",
            "results/kernels.csv",
            "--git-ref",
            "HEAD",
        ],
        text=True,
    )
    assert "new_kernel" not in out
    assert "@ HEAD" in out
    # A table that doesn't exist says where to look
    result = subprocess.run(
        ["calkit", "show", "table", "results/absent.csv"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "calkit list tables" in result.stdout + result.stderr


def test_show_result(tmp_dir):
    _project_with_a_result_and_a_table()
    out = subprocess.check_output(
        ["calkit", "show", "result", "results/summary.json"], text=True
    )
    # Keys are shown dotted, the way a question's evidence names them
    assert "device.change_pct" in out
    assert "-6.25" in out
    out = subprocess.check_output(
        [
            "calkit",
            "show",
            "result",
            "results/summary.json",
            "-k",
            "device.change_pct",
            "--json",
        ],
        text=True,
    )
    assert json.loads(out) == [
        {"key": "device.change_pct", "value": "-6.25", "type": "float"}
    ]
    # The status line stays out of JSON output
    out = subprocess.check_output(
        [
            "calkit",
            "show",
            "result",
            "results/summary.json",
            "-k",
            "speedup_pct",
            "--json",
            "--status",
        ],
        text=True,
    )
    assert json.loads(out)[0]["key"] == "speedup_pct"
    # A key that isn't there names the ones that are
    result = subprocess.run(
        [
            "calkit",
            "show",
            "result",
            "results/summary.json",
            "-k",
            "speedup",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "speedup_pct" in result.stdout + result.stderr
    # A tabular file is a result too, and says how to read it
    result = subprocess.run(
        ["calkit", "show", "result", "results/kernels.csv"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "show table" in result.stdout + result.stderr
