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


def get_value(tex: str, key: str) -> str:
    """The value a generated .tex defines for a key.

    That is, what LaTeX would print for ``\\<command>[<key>]``. Shared by
    the tests that check what ``from-json`` generated.
    """
    match = re.search(
        r"\\pdfstrcmp\{#1\}\{"
        + re.escape(key)
        + r"\}=0%\s*\\def\\\w+@out\{%\s*(.*?)\}%",
        tex,
        flags=re.DOTALL,
    )
    assert match is not None, f"No definition found for '{key}'"
    # Values are wrapped in \\ckvalue{key}{value}{path}{stage}
    wrapped = re.match(
        r"\\ckvalue\{[^}]*\}\{(.*)\}\{[^}]*\}\{[^}]*\}$",
        match.group(1).strip(),
    )
    assert wrapped is not None, match.group(1)
    return wrapped.group(1)


def test_from_json(tmp_dir):
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


def test_from_json_keys_and_collisions(tmp_dir):
    with open("nested.json", "w") as f:
        json.dump(
            {
                "top": 1.5,
                "cases": {"a": {"cp": 0.42}},
                "stations": [{"cf": 0.003}],
                # MATLAB and NumPy write a scalar as a one-element array
                "scale": [3.54],
            },
            f,
        )
    # Named keys reach into nested output, so a value can get to the paper
    # without exposing everything around it
    subprocess.check_call(
        [
            "calkit",
            "latex",
            "from-json",
            "nested.json",
            "-o",
            "out.tex",
            "--command",
            "result",
            "--key",
            "top",
            "--key",
            "cases.a.cp",
            "--key",
            "stations.0.cf",
        ]
    )
    with open("out.tex") as f:
        tex = f.read()
    assert get_value(tex, "top") == "1.5"
    assert get_value(tex, "cases.a.cp") == "0.42"
    assert get_value(tex, "stations.0.cf") == "0.003"
    # Only what was named, so a results file exported wholesale doesn't
    # drag its whole structure into the document
    assert "scale" not in tex
    # A one-element array is the scalar it stands for, printed and
    # formatted as one rather than with its brackets
    subprocess.check_call(
        [
            "calkit",
            "latex",
            "from-json",
            "nested.json",
            "-o",
            "scaled.tex",
            "--command",
            "result",
            "--format-json",
            json.dumps({"scaled": "{scale:.1f}"}),
        ]
    )
    with open("scaled.tex") as f:
        tex = f.read()
    assert get_value(tex, "scale") == "3.54"
    assert get_value(tex, "scaled") == "3.5"
    # A key that isn't there is a typo, not something to leave out
    out = subprocess.run(
        [
            "calkit",
            "latex",
            "from-json",
            "nested.json",
            "-o",
            "x.tex",
            "--key",
            "cases.b.cp",
        ],
        text=True,
        capture_output=True,
    )
    assert out.returncode != 0
    assert "not in nested.json" in out.stderr
    # Merging files that disagree about a key would put a number in the
    # paper from whichever file happened to be read last
    with open("one.json", "w") as f:
        json.dump({"shared": 1}, f)
    with open("two.json", "w") as f:
        json.dump({"shared": 2}, f)
    out = subprocess.run(
        [
            "calkit",
            "latex",
            "from-json",
            "one.json",
            "two.json",
            "-o",
            "y.tex",
        ],
        text=True,
        capture_output=True,
    )
    assert out.returncode != 0
    assert "defined differently" in out.stderr
    # Agreeing about it is fine
    with open("three.json", "w") as f:
        json.dump({"shared": 1}, f)
    subprocess.check_call(
        [
            "calkit",
            "latex",
            "from-json",
            "one.json",
            "three.json",
            "-o",
            "z.tex",
        ]
    )
    # A format spec that cannot apply says so instead of raising
    with open("list.json", "w") as f:
        json.dump({"many": [1, 2, 3]}, f)
    out = subprocess.run(
        [
            "calkit",
            "latex",
            "from-json",
            "list.json",
            "-o",
            "w.tex",
            "--format-json",
            json.dumps({"bad": "{many:.2f}"}),
        ],
        text=True,
        capture_output=True,
    )
    assert out.returncode != 0
    assert "Cannot format 'bad'" in out.stderr


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
    from calkit.cli.latex import DIFF_TMP_DIR
    from calkit.latex import default_base_ref, get_diff_path

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
    assert default_base_ref(repo) == base_sha
    subprocess.check_call(["git", "checkout", "-q", "main"])
    with open("other.txt", "w") as f:
        f.write("landed later\n")
    _commit("third")
    subprocess.check_call(["git", "checkout", "-q", "change"])
    assert default_base_ref(repo) == base_sha
    # Diffs live with the project's other derived files, following
    # executed notebooks, so saving the project tracks them with DVC. A
    # directory per pair, with the document's own path inside it, so two
    # documents both called main.tex don't collide
    assert (
        get_diff_path("paper/main.tex", "v1", "v2")
        == ".calkit/latex-diffs/v1..v2/paper/main.pdf"
    )
    assert (
        get_diff_path("pubs/paper-2/main.tex", "v1", "v2")
        == ".calkit/latex-diffs/v1..v2/pubs/paper-2/main.pdf"
    )
    # A comparison against the working tree can't be reproduced from two
    # commits, so it stays out of the tracked tree
    assert (
        get_diff_path("main.tex", "main")
        == ".calkit/local/latex-diffs/main..working/main.pdf"
    )
    # A ref name is one path component here, whatever it carries
    assert (
        get_diff_path("paper/main.tex", "release/1.0", "release/2.0")
        == ".calkit/latex-diffs/release-1.0..release-2.0/paper/main.pdf"
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
    assert not os.path.isdir(os.path.join(DIFF_TMP_DIR, "base"))
    assert DIFF_TMP_DIR not in subprocess.check_output(
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


def test_marked_up_digest_ignores_the_header():
    # latexdiff writes both inputs' paths and modification times into a
    # header comment, and the older side is a fresh checkout every time,
    # so hashing the file as-is would report a change on every run
    from calkit.cli.latex import _marked_up_digest

    first = (
        b"\\documentclass{article}\n"
        b"%DIF LATEXDIFF DIFFERENCE FILE\n"
        b"%DIF DEL .calkit/local/latex-diff/base/main.tex   Sun Aug 9 06:56:44 2026\n"
        b"%DIF ADD main.tex                                 Sun Aug 9 06:56:30 2026\n"
        b"\\begin{document}Hi\\end{document}\n"
    )
    second = first.replace(b"06:56:44 2026", b"07:10:02 2026").replace(
        b"06:56:30 2026", b"07:10:01 2026"
    )
    assert _marked_up_digest(first) == _marked_up_digest(second)
    # A real change to the document still registers
    changed = first.replace(b"Hi", b"Hello")
    assert _marked_up_digest(changed) != _marked_up_digest(first)


def test_latex_diff_of_one_revision_against_itself(tmp_dir):
    # Two revisions that resolve to the same commit is what a pull request
    # diff looks like from the default branch. The pipeline resolves both
    # ends to commits, so this has to be a result rather than an error, or
    # a stage would fail depending on which branch it ran from.
    subprocess.check_call(["git", "init", "-q", "-b", "main", "."])
    os.makedirs("paper", exist_ok=True)
    with open("paper/main.tex", "w") as f:
        f.write("\\documentclass{article}\n\\begin{document}\nHi\n")
        f.write("\\end{document}\n")
    _commit("first")
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    result = subprocess.run(
        [
            "calkit",
            "latex",
            "diff",
            "paper/main.tex",
            "--from",
            sha,
            "--to",
            sha,
        ],
        capture_output=True,
        text=True,
    )
    assert "Nothing to compare" not in result.stderr
