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
    return match.group(1).strip()


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


def test_from_json_keys(tmp_dir):
    with open("nested.json", "w") as f:
        json.dump(
            {
                "top": 1.5,
                "cases": {"a": {"cp": 0.42}},
                "stations": [{"cf": 0.003}],
                "unused": 9.9,
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
    assert "unused" not in tex
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


@pytest.mark.skipif(
    sys.platform == "win32", reason="Stands in for TeX with shell scripts"
)
def test_latex_diff_dvc_inputs(tmp_dir, tmp_path_factory):
    # Stand-ins for latexdiff and latexmk record what they were given and
    # build a "PDF" from the figures the marked-up document names, so this
    # runs without TeX Live
    import shutil

    from calkit.cli.latex import DIFF_TMP_DIR
    from calkit.latex import get_diff_path

    stubs = tmp_path_factory.mktemp("stubs")
    with open(stubs / "latexdiff", "w") as f:
        f.write(
            "#!/usr/bin/env bash\n"
            '[ "$1" = --version ] && exit 0\n'
            'echo "$@" > "$RECORD_DIR/latexdiff-args.txt"\n'
            'for a in "$@"; do case "$a" in -*) ;; *) cat "$a";; esac; done\n'
        )
    with open(stubs / "latexmk", "w") as f:
        f.write(
            "#!/usr/bin/env bash\n"
            '[ "$1" = --version ] && exit 0\n'
            'echo "$@" > "$RECORD_DIR/latexmk-args.txt"\n'
            'for a in "$@"; do tex="$a"; case "$a" in '
            '-outdir=*) out="${a#-outdir=}";; esac; done\n'
            'cd "$(dirname "$tex")"\n'
            '[ -f setup.tex ] && echo present > "$RECORD_DIR/setup.txt"\n'
            'stem=$(basename "$tex" .tex)\n'
            'if [ -n "$FAIL" ]; then\n'
            '  printf "junk\\n! Undefined control sequence.\\nl.3 \\\\oops\\n"'
            ' > "$out/$stem.log"\n'
            "  exit 12\n"
            "fi\n"
            ': > "$out/$stem.pdf"\n'
            "for fig in $(sed -n 's/.*includegraphics{\\([^}]*\\)}.*/\\1/p'"
            ' "$stem.tex"); do cat "$fig"* >> "$out/$stem.pdf"; done\n'
        )
    for name in ["latexdiff", "latexmk"]:
        os.chmod(stubs / name, 0o755)
    env = os.environ | {
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "RECORD_DIR": str(stubs),
    }
    # A figure tracked with DVC that changes between two revisions
    subprocess.check_call(["git", "init", "-q", "-b", "main", "."])
    subprocess.check_call(["calkit", "dvc", "init", "-q"])
    os.makedirs("paper/figs")
    with open("paper/main.tex", "w", encoding="utf-8") as f:
        f.write("\\documentclass{article}\n")
        f.write("\\newcommand{\\wc}[1]{\\verbatiminput{#1.wcsum}}\n")
        f.write("\\begin{document}\nGreen\u2019s function\n")
        f.write("\\includegraphics{figs/plot}\n\\end{document}\n")
    with open("paper/.latexmkrc", "w") as f:
        f.write("$aux_dir = 'aux';\n")
    with open("paper/figs/plot.png", "w") as f:
        f.write("old\n")
    subprocess.check_call(["calkit", "dvc", "add", "-q", "paper/figs"])
    # A copy another stage makes, which DVC records but doesn't store
    os.makedirs("shared")
    with open("shared/setup.tex", "w") as f:
        f.write("% setup\n")
    with open("dvc.yaml", "w") as f:
        f.write(
            "stages:\n"
            "  copy-setup:\n"
            "    cmd: cp shared/setup.tex paper/setup.tex\n"
            "    deps: [shared/setup.tex]\n"
            "    outs:\n"
            "      - paper/setup.tex:\n"
            "          cache: false\n"
        )
    with open(".gitignore", "a") as f:
        f.write("/paper/setup.tex\n")
    subprocess.check_call(["calkit", "dvc", "repro", "-q"])
    _commit("first")
    subprocess.check_call(["git", "tag", "v1"])
    with open("paper/figs/plot.png", "w") as f:
        f.write("new\n")
    subprocess.check_call(["calkit", "dvc", "add", "-q", "paper/figs"])
    _commit("second")
    # Neither side can come from the working tree
    shutil.rmtree("paper/figs")
    diff = [
        "calkit",
        "latex",
        "diff",
        "paper/main.tex",
        "--from",
        "v1",
        "-r",
        "paper/.latexmkrc",
    ]
    cmd = diff + [
        "--to",
        "HEAD",
        "--latexdiff-arg",
        "--graphics-markup=both",
        "--input",
        "paper/figs/",
        "--input",
        "paper/setup.tex",
        "--keep-tex",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    # Each side shows its own revision's figure: the older side's is
    # repointed at its checkout, since it changed, and the newer side's is
    # fetched into the checkout the document is built in. Relative, so it
    # resolves inside a container too.
    output = get_diff_path("paper/main.tex", "v1", "HEAD")
    with open(output) as f:
        assert f.read() == "old\nnew\n"
    with open("paper/main-diff.tex", encoding="utf-8") as f:
        marked_up = f.read()
    # A verbatim input named by a macro parameter is broken onto its own
    # line in each checkout rather than by latexdiff's --filter-script,
    # which mangles non-ASCII text
    assert "\\verbatiminput%\n{#1.wcsum}" in marked_up
    assert "Green\u2019s function" in marked_up
    with open(stubs / "latexdiff-args.txt") as f:
        assert "--filter-script" not in f.read()
    assert "\\includegraphics{../../base/paper/figs/plot.png}" in marked_up
    assert "\\includegraphics{figs/plot}" in marked_up
    assert not os.path.exists("paper/figs")
    # The diff is built with the document's rc file, read before the
    # directories Calkit sets so those win, and latexdiff gets its options
    with open(stubs / "latexmk-args.txt") as f:
        latexmk_args = f.read().split()
    rc = latexmk_args[latexmk_args.index("-r") + 1]
    assert rc.endswith("latex-diff-build/head/paper/.latexmkrc")
    auxdir = next(a for a in latexmk_args if a.startswith("-auxdir="))
    assert latexmk_args.index("-r") < latexmk_args.index(auxdir)
    with open(stubs / "latexdiff-args.txt") as f:
        assert "--graphics-markup=both" in f.read()
    # An output DVC doesn't store is copied from the working tree, since no
    # checkout can have it
    with open(stubs / "setup.txt") as f:
        assert f.read() == "present\n"
    assert DIFF_TMP_DIR not in subprocess.check_output(
        ["git", "worktree", "list"], text=True
    )
    # Fetched without --input too, since a directory DVC tracks as a whole
    # beside the document is included
    result = subprocess.run(
        diff + ["--to", "HEAD", "--force"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    with open(output) as f:
        assert f.read() == "old\nnew\n"
    # Changing how a comparison between fixed revisions is built rebuilds
    # it, since the pipeline only runs it when something has changed
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    for markup in ["CFONT", "UNDERLINE"]:
        result = subprocess.run(
            diff + ["--to", head_sha, "--latexdiff-arg", f"--type={markup}"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        with open(stubs / "latexdiff-args.txt") as f:
            assert f"--type={markup}" in f.read()
    # Against the working tree, a changed figure or rc file rebuilds the
    # diff even though the marked-up source is the same
    working_output = get_diff_path("paper/main.tex", "v1")
    os.makedirs("paper/figs")
    for content in ["newer\n", "newest\n"]:
        with open("paper/figs/plot.png", "w") as f:
            f.write(content)
        result = subprocess.run(diff, capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr
        with open(working_output) as f:
            assert f.read() == "old\n" + content
    os.remove(stubs / "latexmk-args.txt")
    result = subprocess.run(diff, capture_output=True, text=True, env=env)
    assert "is up to date" in result.stdout
    assert not os.path.exists(stubs / "latexmk-args.txt")
    with open("paper/.latexmkrc", "a") as f:
        f.write("$max_repeat = 5;\n")
    result = subprocess.run(diff, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert os.path.exists(stubs / "latexmk-args.txt")
    # -silent hides why latexmk failed, so the errors LaTeX logged are shown
    result = subprocess.run(
        cmd + ["--force"],
        capture_output=True,
        text=True,
        env=env | {"FAIL": "1"},
    )
    assert result.returncode != 0
    assert "! Undefined control sequence." in result.stderr
    assert "l.3 \\oops" in result.stderr
    assert "exit status 12" in result.stderr


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


@skipif_windows_docker
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
    # A verbatim input that's a macro parameter used to make latexdiff try
    # to open, e.g., '#1.wcsum' and fail
    with open("paper/main.tex", "w") as f:
        f.write("\\documentclass{article}\n\\usepackage{verbatim}\n")
        f.write("\\newcommand{\\wc}[1]{\\verbatiminput{#1.wcsum}}\n")
        f.write("\\begin{document}\nHi\n\\end{document}\n")
    _commit("macro")
    result = subprocess.run(
        ["calkit", "latex", "diff", "paper/main.tex", "--from", sha],
        capture_output=True,
        text=True,
    )
    assert "Couldn't open" not in result.stderr
    assert result.returncode == 0, result.stderr
