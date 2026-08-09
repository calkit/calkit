"""Tests for ``calkit.cli.latex.``"""

import json
import os
import re
import subprocess
import sys

import pytest

import calkit
import calkit.git

skipif_windows_docker = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "TODO: Docker Linux images are unavailable on windows-latest GHA "
        "runners"
    ),
)


def test_from_json(tmp_dir):
    # Extract the value defined for a given key in a generated .tex file,
    # i.e., what LaTeX would print for \<command>[<key>]
    def get_value(tex: str, key: str) -> str:
        match = re.search(
            r"\\pdfstrcmp\{#1\}\{"
            + re.escape(key)
            + r"\}=0%\s*\\def\\\w+@out\{%\s*(.*?)\}%",
            tex,
            flags=re.DOTALL,
        )
        assert match is not None, f"No definition found for '{key}'"
        return match.group(1).strip()

    # Test setup
    data = {"sup": 5.555, "lol": 3}
    with open("test.json", "w") as f:
        json.dump(data, f)
    with open("test2.json", "w") as f:
        json.dump({"hehe": 77}, f)
    fmt_dict = {
        "result1": "{sup / lol * 1e5 + 22:.1f}",
        "result2": "sup is {sup} and lol is {lol}",
        "result3": "{sup**3 * 1e12:.1e}",
        "lol": "{lol}",
    }
    # Note the output directory does not exist yet, so this also checks it
    # gets created
    subprocess.run(
        [
            "calkit",
            "latex",
            "from-json",
            "test.json",
            "test2.json",
            "-o",
            "paper/results.tex",
            "--output",
            "paper/results2.tex",
            "--command",
            "theresults",
            "--format-json",
            json.dumps(fmt_dict),
        ],
        check=True,
    )
    # Check the generated LaTeX defines the command and the correct values
    with open("paper/results.tex") as f:
        tex = f.read()
    assert r"\newcommand\theresults" in tex
    assert get_value(tex, "sup") == "5.555"
    assert get_value(tex, "hehe") == "77"
    assert get_value(tex, "result1") == "185188.7"
    assert get_value(tex, "result2") == "sup is 5.555 and lol is 3"
    assert get_value(tex, "result3") == "1.7e+14"
    assert get_value(tex, "lol") == "3"
    # Both output files should have been written with the same content
    with open("paper/results2.tex") as f:
        assert f.read() == tex
    # Now test some input validation
    with open("bad.json", "w") as f:
        f.write("not valid json")
    out = subprocess.run(
        [
            "calkit",
            "latex",
            "from-json",
            "bad.json",
            "--output",
            "paper/results.tex",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert out.returncode != 0
    assert "not valid JSON" in out.stderr
    # Test that we can supply multiple input files
    with open("test2.json", "w") as f:
        json.dump({"result4": "hello"}, f)
    subprocess.run(
        [
            "calkit",
            "latex",
            "from-json",
            "test.json",
            "test2.json",
            "-o",
            "paper/results.tex",
            "--format-json",
            json.dumps(fmt_dict),
        ],
        check=True,
    )
    with open("paper/results.tex") as f:
        tex = f.read()
    # Without --command, the command name comes from the output file name
    assert r"\newcommand\results" in tex
    assert get_value(tex, "result4") == "hello"
    assert get_value(tex, "sup") == "5.555"


@skipif_windows_docker
def test_build(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    os.makedirs("paper", exist_ok=True)
    with open("paper/main.tex", "w") as f:
        f.write(
            r"""\documentclass{article}
            \begin{document}
            Hello, world!
            \end{document}
            """
        )
    subprocess.check_call(["calkit", "latex", "build", "paper/main.tex"])
    assert os.path.isfile("paper/main.pdf")


@skipif_windows_docker
def test_build_output_and_aux_dirs(tmp_dir):
    # --output-dir / --aux-dir are given relative to the current directory but
    # latexmk runs with -cd, so the build command must translate them to the
    # .tex file's frame. The PDF should land in <output-dir> and aux files in
    # <aux-dir>, both resolved from the project root.
    os.makedirs("paper", exist_ok=True)
    with open("paper/main.tex", "w") as f:
        f.write(
            r"""\documentclass{article}
            \begin{document}
            Hello, world!
            \end{document}
            """
        )
    subprocess.check_call(
        [
            "calkit",
            "latex",
            "build",
            "--output-dir",
            "paper/build",
            "--aux-dir",
            "paper/aux",
            "paper/main.tex",
        ]
    )
    assert os.path.isfile("paper/build/main.pdf")
    assert not os.path.isfile("paper/main.pdf")
    assert os.path.isfile("paper/aux/main.aux")


def _commit(message: str) -> None:
    subprocess.check_call(["git", "add", "-A"])
    subprocess.check_call(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=T",
            "commit",
            "-qm",
            message,
        ]
    )


def test_latex_diff_setup(tmp_dir):
    # Everything up to running latexdiff itself, which needs TeX Live and
    # so can't run in CI: which revision gets compared, and that the
    # worktree it checks out is always cleaned up
    from calkit.cli.latex import (
        DIFF_WORKTREE_DIR,
        _default_base_ref,
        get_diff_path,
    )

    subprocess.check_call(["git", "init", "-q", "-b", "main", "."])
    os.makedirs("paper", exist_ok=True)
    with open("paper/main.tex", "w") as f:
        f.write("\\documentclass{article}\n\\begin{document}\nHi\n\\end{doc")
        f.write("ument}\n")
    _commit("first")
    base_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    subprocess.check_call(["git", "checkout", "-qb", "change"])
    with open("paper/main.tex", "a") as f:
        f.write("% edited\n")
    _commit("second")
    # The merge base, not the tip: work that lands on the default branch
    # after a branch starts isn't part of that branch's change
    repo = calkit.git.get_repo()
    assert _default_base_ref(repo) == base_sha
    subprocess.check_call(["git", "checkout", "-q", "main"])
    with open("other.txt", "w") as f:
        f.write("landed later\n")
    _commit("third")
    subprocess.check_call(["git", "checkout", "-q", "change"])
    assert _default_base_ref(repo) == base_sha
    # Diffs live with the project's other derived files, following
    # executed notebooks, so saving the project tracks them with DVC
    assert (
        get_diff_path("paper/main.tex", "submitted-v1")
        == ".calkit/latex-diff/paper/main/submitted-v1.pdf"
    )
    assert (
        get_diff_path("main.tex") == ".calkit/latex-diff/main/merge-base.pdf"
    )
    # A ref name is one path component here, whatever it carries
    assert (
        get_diff_path("paper/main.tex", "release/1.0")
        == ".calkit/latex-diff/paper/main/release-1.0.pdf"
    )
    # A document that doesn't exist at the base revision is an error, and
    # the checked-out copy is removed either way
    subprocess.check_call(["git", "checkout", "-qb", "new-doc"])
    os.makedirs("paper2", exist_ok=True)
    with open("paper2/new.tex", "w") as f:
        f.write("\\documentclass{article}\n")
    _commit("new document")
    result = subprocess.run(
        ["calkit", "latex", "diff", "paper2/new.tex", "--from", base_sha],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "does not exist at" in result.stderr
    assert not os.path.isdir(DIFF_WORKTREE_DIR)
    assert DIFF_WORKTREE_DIR not in subprocess.check_output(
        ["git", "worktree", "list"], text=True
    )
    # An unknown revision fails before touching anything
    result = subprocess.run(
        ["calkit", "latex", "diff", "paper2/new.tex", "--from", "nope"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "was not found" in result.stderr
    result = subprocess.run(
        ["calkit", "latex", "diff", "paper2/missing.tex"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "does not exist" in result.stderr
