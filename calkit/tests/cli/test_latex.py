"""Tests for ``calkit.cli.latex.``"""

import json
import os
import re
import subprocess
import sys

import pytest

import calkit
import calkit.git
import calkit.pipeline

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
    assert not os.listdir(DIFF_TMP_DIR)
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
            '[ -n "$SLOW" ] && sleep 1\n'
            '[ -f setup.tex ] && echo present > "$RECORD_DIR/setup.txt"\n'
            'stem=$(basename "$tex" .tex)\n'
            'if [ -n "$FAIL" ]; then\n'
            '  printf "junk\\n! Undefined control sequence.\\nl.3 \\\\oops\\n"'
            ' > "$out/$stem.log"\n'
            '  [ -n "$PARTIAL" ] && : > "$out/$stem.pdf"\n'
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
        f.write("\\newcommand{\\singlecol}[1]{\\onecolumn{#1}\\twocolumn}\n")
        f.write("\\begin{document}\nGreen\u2019s function\n")
        f.write("\\includegraphics{figs/plot}\n")
        # What latexdiff's figure markup leaves in a table it marked up
        f.write("\\DIFaddendFL \\hline \\DIFaddbeginFL \\label{x}\n")
        f.write("\\singlecol{\n\\input{setup}\n}\n\\end{document}\n")
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
        "--graphics-markup=new-only",
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
    # --keep-tex keeps what latexdiff saw beside the diff PDF, so a
    # --flatten or macro expansion failure can be inspected
    kept_stem = output.removesuffix(".pdf")
    assert not os.path.exists("paper/main-diff.tex")
    with open(f"{kept_stem}-diff.tex", encoding="utf-8") as f:
        marked_up = f.read()
    # A verbatim input named by a macro parameter is broken onto its own
    # line in each checkout rather than by latexdiff's --filter-script,
    # which mangles non-ASCII text
    assert "\\verbatiminput%\n{#1.wcsum}" in marked_up
    assert "Green\u2019s function" in marked_up
    # A figure marker can't come before anything starting a table row
    assert "\\DIFaddendFL \\hline" not in marked_up
    assert "\\hline \\DIFaddbeginFL \\label{x}" in marked_up
    with open(stubs / "latexdiff-args.txt") as f:
        latexdiff_args = f.read()
    assert "--filter-script" not in latexdiff_args
    # A macro wrapping a block is expanded, so latexdiff compares what it
    # wraps rather than one token or a table marked up as text
    assert "--append-textcmd" not in latexdiff_args
    assert (
        "\\onecolumn\\begingroup \n\\input{setup}\n\\endgroup \\twocolumn"
        in (marked_up)
    )
    assert "\\includegraphics{../../base/paper/figs/plot.png}" in marked_up
    assert "\\includegraphics{figs/plot}" in marked_up
    assert not os.path.exists("paper/figs")
    with open(f"{kept_stem}-old.tex", encoding="utf-8") as f:
        old_tex = f.read()
    with open(f"{kept_stem}-new.tex", encoding="utf-8") as f:
        new_tex = f.read()
    assert "\\verbatiminput%\n{#1.wcsum}" in old_tex
    assert "\\verbatiminput%\n{#1.wcsum}" in new_tex
    assert "../../base/paper/figs/plot.png" in old_tex
    assert "../../base/paper/figs/plot.png" not in new_tex
    # The diff is built with the document's rc file, read before the
    # directories Calkit sets so those win, and latexdiff gets its options
    with open(stubs / "latexmk-args.txt") as f:
        latexmk_args = f.read().split()
    rc = latexmk_args[latexmk_args.index("-r") + 1]
    assert rc.endswith("/head/paper/.latexmkrc")
    auxdir = next(a for a in latexmk_args if a.startswith("-auxdir="))
    assert latexmk_args.index("-r") < latexmk_args.index(auxdir)
    # Inside the directory the document is built in, since TeX refuses to
    # write anywhere else and makeindex runs from inside it for glossaries
    assert auxdir == "-auxdir=calkit-latex-diff-aux"
    # An explicit --graphics-markup replaces Calkit's default
    with open(stubs / "latexdiff-args.txt") as f:
        latexdiff_args = f.read().split()
    assert "--graphics-markup=new-only" in latexdiff_args
    assert "--graphics-markup=both" not in latexdiff_args
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
    # Changed figures are shown old and new by default, since each side has
    # its own revision's figures
    with open(stubs / "latexdiff-args.txt") as f:
        assert "--graphics-markup=both" in f.read().split()
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
    # A file of the user's with the marked-up document's name is left alone
    with open("paper/main-diff.tex", "w") as f:
        f.write("mine\n")
    for content in ["newer\n", "newest\n"]:
        with open("paper/figs/plot.png", "w") as f:
            f.write(content)
        result = subprocess.run(diff, capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr
        with open(working_output) as f:
            assert f.read() == "old\n" + content
    # Building beside the working tree's document leaves nothing behind
    assert not [p for p in os.listdir("paper") if "calkit-latex-diff" in p]
    with open("paper/main-diff.tex") as f:
        assert f.read() == "mine\n"
    # A run that was killed leaves its checkout behind, which the next
    # one clears away
    dead_run = os.path.join(DIFF_TMP_DIR, "999999999")
    os.makedirs(os.path.join(dead_run, "base"))
    # Two at once, e.g., from the editor while the pipeline runs, don't
    # build over each other
    procs = [
        subprocess.Popen(
            diff + ["--force", "-o", f"at-once-{n}.pdf"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env | {"SLOW": "1"},
        )
        for n in range(2)
    ]
    for n, proc in enumerate(procs):
        _, stderr = proc.communicate()
        assert proc.returncode == 0, stderr
        with open(f"at-once-{n}.pdf") as f:
            assert f.read() == "old\nnewest\n"
    assert not os.path.exists(dead_run)
    os.remove(stubs / "latexmk-args.txt")
    os.remove(stubs / "latexdiff-args.txt")
    result = subprocess.run(diff, capture_output=True, text=True, env=env)
    assert "is up to date" in result.stdout
    assert not os.path.exists(stubs / "latexmk-args.txt")
    # Known from what it's made of, so latexdiff doesn't run either
    assert not os.path.exists(stubs / "latexdiff-args.txt")
    with open("paper/.latexmkrc", "a") as f:
        f.write("$max_repeat = 5;\n")
    result = subprocess.run(diff, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert os.path.exists(stubs / "latexmk-args.txt")
    # A filter rewrites the marked-up document before it's built, and the
    # working tree's sources are prepared like a checkout's, in a copy
    with open("filter.py", "w") as f:
        f.write(
            "import sys\n"
            "text = sys.stdin.read()\n"
            "sys.stdout.write(text.replace(sys.argv[1], sys.argv[2]))\n"
        )
    filter_args = ["--filter-script", "filter.py"]
    filter_args += ["--filter-arg", "Green", "--filter-arg", "Blue"]
    result = subprocess.run(
        diff + filter_args + ["--keep-tex"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    working_stem = working_output.removesuffix(".pdf")
    with open(f"{working_stem}-diff.tex", encoding="utf-8") as f:
        assert "Green" not in f.read()
    with open(f"{working_stem}-new.tex", encoding="utf-8") as f:
        assert "\\onecolumn\\begingroup" in f.read()
    with open("paper/main.tex", encoding="utf-8") as f:
        assert "\\singlecol{" in f.read()
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
    assert "exit code 12" in result.stderr
    # A PDF latexmk built despite errors is kept, with a warning, since a
    # diff that's mostly right is more use than none
    result = subprocess.run(
        cmd + ["--force"],
        capture_output=True,
        text=True,
        env=env | {"FAIL": "1", "PARTIAL": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert "! Undefined control sequence." in result.stderr
    assert "built despite the LaTeX errors" in result.stderr
    with open(stubs / "latexmk-args.txt") as f:
        assert "-f" in f.read().split()
    # Detection can't find another stage's uncached output at a revision
    os.remove(stubs / "setup.txt")
    bare = ["calkit", "latex", "diff", "paper/main.tex", "--from", "v1"]
    bare += ["--to", "HEAD", "--force"]
    result = subprocess.run(bare, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert not os.path.exists(stubs / "setup.txt")
    # But a document the pipeline builds is diffed the way its stage builds
    # it, fetching what the compiled stage depends on
    with open("calkit.yaml", "w") as f:
        f.write(
            "pipeline:\n"
            "  stages:\n"
            "    paper:\n"
            "      kind: latex\n"
            "      target_path: paper/main.tex\n"
            "      latexmkrc_path: paper/.latexmkrc\n"
            "      latexdiff_args: [--type=CFONT]\n"
        )
    with open("dvc.yaml", "a") as f:
        f.write(
            "  paper:\n"
            "    cmd: calkit latex build paper/main.tex\n"
            "    deps: [paper/main.tex, paper/.latexmkrc, paper/setup.tex]\n"
        )
    result = subprocess.run(bare, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    with open(stubs / "setup.txt") as f:
        assert f.read() == "present\n"
    with open(stubs / "latexdiff-args.txt") as f:
        assert "--type=CFONT" in f.read().split()
    with open(stubs / "latexmk-args.txt") as f:
        latexmk_args = f.read().split()
    assert latexmk_args[latexmk_args.index("-r") + 1].endswith(
        "paper/.latexmkrc"
    )
    # A revision's data comes from a remote through the project's cache, so
    # the next comparison against it needn't download anything
    import hashlib

    remote = tmp_path_factory.mktemp("remote") / "store"
    subprocess.check_call(
        ["calkit", "dvc", "remote", "add", "-d", "r", remote]
    )
    # A local remote is laid out like the cache, and DVC won't push data for
    # a revision from before the remote existed
    shutil.move(".dvc/cache", remote)
    result = subprocess.run(bare, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    old_md5 = hashlib.md5(b"old\n").hexdigest()
    assert os.path.isfile(f".dvc/cache/files/md5/{old_md5[:2]}/{old_md5[2:]}")


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


def test_get_source_date_epoch(tmp_dir):
    from calkit.latex import get_source_date_epoch

    # Outside a repo there's nothing to read a date from
    os.makedirs("paper")
    with open(os.path.join("paper", "main.tex"), "w") as f:
        f.write("\\documentclass{article}\\begin{document}Hi\\end{document}\n")
    assert get_source_date_epoch("paper/main.tex") is None
    subprocess.check_call(["git", "init", "-q"])
    subprocess.check_call(["git", "add", "paper/main.tex"])
    subprocess.check_call(["git", "commit", "-q", "-m", "Add the paper"])
    committed = subprocess.check_output(
        ["git", "log", "-1", "--format=%ct"], text=True
    ).strip()
    assert get_source_date_epoch("paper/main.tex") == committed
    # A commit elsewhere doesn't restamp a document it didn't touch
    with open("notes.txt", "w") as f:
        f.write("sup\n")
    subprocess.check_call(["git", "add", "notes.txt"])
    subprocess.check_call(
        ["git", "commit", "-q", "-m", "Add notes", "--date", "2030-01-01"]
    )
    assert get_source_date_epoch("paper/main.tex") == committed
    # Build artifacts are untracked, and say nothing about the source
    with open(os.path.join("paper", "main.log"), "w") as f:
        f.write("log\n")
    assert get_source_date_epoch("paper/main.tex") == committed
    # An edit in the working tree can only have been made now
    with open(os.path.join("paper", "main.tex"), "a") as f:
        f.write("% edit\n")
    assert get_source_date_epoch("paper/main.tex") is None


def test_fetch_missing_packages(tmp_dir, monkeypatch):
    from calkit.cli import latex as cli_latex
    from calkit.latex import find_missing_tex_files

    # What LaTeX says, for a style file and for a font it has no metrics for
    log = (
        "! LaTeX Error: File `xurl.sty' not found.\n"
        "! Font OT1/pcr/m/n/10=pcrr7t at 10.0pt not loadable: Metric (TFM) "
        "file not found.\n"
        "! LaTeX Error: File `xurl.sty' not found.\n"
    )
    assert find_missing_tex_files(log) == ["xurl.sty", "pcrr7t.tfm"]
    assert find_missing_tex_files("Output written on main.pdf") == []
    os.makedirs("paper")
    log_path = os.path.join("paper", "main.log")
    fdb_path = os.path.join("paper", "main.fdb_latexmk")
    calls: list[list[str]] = []
    # Each build writes the log LaTeX would, missing what isn't installed
    state = {"installed": set(), "unfetchable": set()}

    def latexmk(cmd):
        missing = {"xurl.sty"} - state["installed"]
        missing |= state["unfetchable"]
        with open(log_path, "w") as f:
            for name in missing:
                f.write(f"! LaTeX Error: File `{name}' not found.\n")
        with open(fdb_path, "w") as f:
            f.write("fdb")
        if missing:
            raise subprocess.CalledProcessError(12, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "latexmk":
            captured.append(kwargs.get("capture_output"))
            return latexmk(cmd)
        if "search" in cmd:
            name = cmd[-1].lstrip("/")
            out = f"{name.split('.')[0]}:\n\ttexmf-dist/tex/latex/x/{name}\n"
            return subprocess.CompletedProcess(cmd, 0, stdout=out)
        assert "install" in cmd
        state["installed"] |= {"xurl.sty"}
        # As a font's install does, failing on the map after the files land
        return subprocess.CompletedProcess(cmd, 1, stdout="")

    captured: list[bool] = []
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(calkit, "check_dep_exists", lambda dep: False)
    monkeypatch.setattr(
        calkit.docker, "ensure_image_available", lambda image: None
    )

    def build(quiet: bool = False):
        return cli_latex._run_latexmk(
            ["latexmk", "paper/main.tex"],
            env=None,
            log_path=log_path,
            fdb_path=fdb_path,
            environment=None,
            verbose=False,
            quiet=quiet,
        )

    # Fetched into the project and built on the retry, the install's error
    # notwithstanding, with latexmk made to try again
    assert build() == 0
    installs = [c for c in calls if "install" in c]
    assert len(installs) == 1 and installs[0][-1] == "xurl"
    assert "TEXMFHOME=/work/.calkit/local/texmf" in installs[0]
    assert os.path.isdir(os.path.join(".calkit", "local", "texmf"))
    # Something fetching doesn't fix fails rather than looping
    state["installed"].clear()
    state["unfetchable"] = {"nope.sty"}
    calls.clear()
    assert build() == 12
    assert len([c for c in calls if c[0] == "latexmk"]) == 2
    # A system TeX is the user's, so nothing is fetched into it
    monkeypatch.setattr(calkit, "check_dep_exists", lambda dep: True)
    calls.clear()
    assert build() == 12
    assert not [c for c in calls if "tlmgr" in c]
    # Quiet keeps latexmk's output out of the way, for a caller that reports
    # what went wrong from the log
    captured.clear()
    build(quiet=True)
    assert captured == [True]


def test_from_questions(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    with open("results.json", "w") as f:
        json.dump({"gain": 0.25}, f)
    ck_info = calkit.load_calkit_info()
    ck_info["questions"] = [
        {
            "name": "staging",
            "question": "Does staging help?",
            "answer": "Yes, by {gain:+.2f} on 50% & more_problems.",
            "evidence": [
                {
                    "kind": "value",
                    "path": "results.json",
                    "key": "gain",
                    "name": "gain",
                }
            ],
        }
    ]
    ck_info["pipeline"] = {
        "stages": {
            "qa": {
                "kind": "questions-to-latex",
                "outputs": ["paper/qa.tex"],
                "command_name": "qa",
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # The compiled stage reads calkit.yaml and the evidence
    stage = calkit.pipeline.to_dvc()["qa"]
    assert stage["cmd"] == (
        "calkit latex from-questions --output paper/qa.tex --command qa"
    )
    assert set(stage["deps"]) >= {"calkit.yaml", "results.json"}
    subprocess.check_call(["calkit", "run"])
    with open("paper/qa.tex") as f:
        tex = f.read()
    # Rendered, then escaped for LaTeX
    assert "\\newcommand\\qa" in tex
    assert "Yes, by +0.25 on 50\\% \\& more\\_problems." in tex
    assert "{staging.answer}" in tex and "{1.question}" in tex
    # A change to the evidence reruns the stage
    with open("results.json", "w") as f:
        json.dump({"gain": -0.1}, f)
    subprocess.check_call(["calkit", "run"])
    with open("paper/qa.tex") as f:
        # json2latex braces a hyphen so it can't form a ligature
        assert "Yes, by {-}0.10" in f.read()
    # A template that can't render fails rather than writing a placeholder
    ck_info["questions"][0]["answer"] = "Up {missing}."
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    result = subprocess.run(
        ["calkit", "latex", "from-questions", "-o", "x.tex"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and not os.path.exists("x.tex")
    # A bad output path fails before any other output is written
    ck_info["questions"][0]["answer"] = "Yes."
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    result = subprocess.run(
        ["calkit", "latex", "from-questions", "-o", "a.tex", "-o", "b.txt"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and not os.path.exists("a.tex")
    # The stage reads from the project root, so it can't set a wdir
    ck_info["pipeline"]["stages"]["qa"]["wdir"] = "paper"
    with pytest.raises(Exception, match="wdir"):
        calkit.pipeline.to_dvc(ck_info=ck_info)


def test_comments(tmp_dir):
    def ck(*args: str) -> str:
        return subprocess.run(
            ["calkit", "latex", "comments", *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    os.makedirs("paper")
    with open("paper/main.tex", "w") as f:
        f.write(
            "\\begin{document}\n"
            "\\input{intro}\n"
            "\n"
            "First paragraph,\n"
            "over two lines.\n"
            "\n"
            "Second paragraph.\n"
            "\\begin{equation}\n"
            "  E = \\alpha m c^2\n"
            "\\end{equation}\n"
            "\\end{document}\n"
        )
    with open("paper/intro.tex", "w") as f:
        f.write(
            "% COMMENT\n"
            "%   T. Author:\n"
            "%     A thread without an ID.\n"
            "Intro text.\n"
        )
    # Listing follows inputs, and anchors each thread to the paragraph
    # below it
    listed = json.loads(ck("list", "paper/main.tex", "--json"))
    assert len(listed) == 1 and listed[0]["path"] == "paper/intro.tex"
    assert listed[0]["id"] is None and listed[0]["line"] == 1
    assert listed[0]["anchor"]["text"] == "Intro text."
    # Adding at any line in a paragraph puts the thread above it, with an
    # ID and the author from Git
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "config", "user.name", "Ann Author"], check=True)
    subprocess.run(["git", "config", "user.email", "ann@x.org"], check=True)
    added = json.loads(
        ck(
            "add",
            "paper/main.tex",
            "--line",
            "5",
            "-m",
            "Clarify.",
            "--highlight",
            "two lines",
            "--json",
        )
    )
    id_ = added["id"]
    assert re.fullmatch(r"[0-9a-f]{8}", id_)
    assert added["anchor"]["line"] == added["line"] + added["nlines"]
    assert added["anchor"]["text"] == "First paragraph, over two lines."
    assert added["messages"][0]["author"] == "Ann Author"
    assert added["messages"][0]["email"] == "ann@x.org"
    with open("paper/main.tex") as f:
        lines = f.read().split("\n")
    assert lines[3] == (f'% COMMENT id={id_} highlight={{text: "two lines"}}')
    assert lines[4].startswith("%   Ann Author <ann@x.org> (")
    # A second thread on the same paragraph goes below the first
    id2 = ck("add", "paper/main.tex", "-l", "8", "-m", "Also.")
    listed = json.loads(ck("list", "paper/main.tex", "--json"))
    assert [c["id"] for c in listed[1:]] == [id_, id2]
    assert listed[1]["anchor"] == listed[2]["anchor"]
    assert listed[0]["path"] == "paper/intro.tex"
    # Replying and resolving by ID
    ck("reply", "paper/main.tex", "--id", id_, "-m", "Done.", "--author", "B")
    ck("resolve", "paper/main.tex", "--id", id_)
    listed = json.loads(ck("list", "paper/main.tex", "--json"))
    thread = next(c for c in listed if c["id"] == id_)
    assert thread["resolved"]
    assert [m["text"] for m in thread["messages"]] == ["Clarify.", "Done."]
    assert thread["highlight"] == {"text": "two lines", "occ": 0}
    unresolved = json.loads(ck("list", "paper/main.tex", "-u", "--json"))
    assert id_ not in [c["id"] for c in unresolved]
    ck("reopen", "paper/main.tex", "--id", id_)
    listed = json.loads(ck("list", "paper/main.tex", "--json"))
    assert not next(c for c in listed if c["id"] == id_)["resolved"]
    # A thread without an ID gets one when it's first edited by line
    new_id = ck("resolve", "paper/intro.tex", "--line", "2")
    with open("paper/intro.tex") as f:
        assert f.read().startswith(f"% COMMENT id={new_id} resolved=true\n")
    # Deleting removes the whole thread and nothing else
    ck("delete", "paper/main.tex", "--id", id2)
    listed = json.loads(ck("list", "paper/main.tex", "--json"))
    assert id2 not in [c["id"] for c in listed]
    with open("paper/main.tex") as f:
        assert "Also." not in f.read()
    # A paragraph is found from rendered text, e.g., a line of the PDF, or
    # from a line in its source
    found = json.loads(
        ck(
            "locate",
            "paper/main.tex",
            "--text",
            "First paragraph, over two",
            "--json",
        )
    )
    assert found["path"] == "paper/main.tex"
    assert found["text"] == "First paragraph, over two lines."
    assert (found["end_line"] - found["line"]) == 1
    found = json.loads(
        ck(
            "locate",
            "paper/main.tex",
            "--path",
            "paper/intro.tex",
            "--line",
            "1",
            "--json",
        )
    )
    assert found["text"] == "Intro text."
    assert ck("locate", "paper/main.tex", "--text", "Intro text").startswith(
        "paper/intro.tex:"
    )
    # An equation has few words or none, so it's found by its symbols, as
    # typeset, with its number
    found = json.loads(
        ck("locate", "paper/main.tex", "--text", "E = \u03b1mc2 (1)", "--json")
    )
    assert found["text"] == "E = \u03b1 m c 2"
    with open("paper/main.tex") as f:
        assert f.read().split("\n")[found["line"] - 1] == "\\begin{equation}"
    # Bad references fail
    for args in [
        ["resolve", "paper/main.tex", "--id", "nope"],
        ["resolve", "paper/main.tex"],
        ["add", "paper/main.tex", "-l", "99", "-m", "x"],
        ["locate", "paper/main.tex", "--text", "Nothing like this anywhere"],
    ]:
        res = subprocess.run(
            ["calkit", "latex", "comments", *args], capture_output=True
        )
        assert res.returncode != 0


def test_from_markdown(tmp_dir):
    import calkit.docx

    if calkit.docx.find_pandoc() is None:
        pytest.skip("Pandoc isn't available")
    os.makedirs("results")
    with open("results/r.json", "w") as f:
        json.dump({"gain": 2.0, "other": 3}, f)
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "owner": "someone",
                "name": "proj",
                "questions": [
                    {
                        "question": "Other?",
                        "answer": "{o}",
                        "evidence": [
                            {
                                "kind": "value",
                                "path": "results/r.json",
                                "key": "other",
                                "name": "o",
                            }
                        ],
                    },
                    {
                        "question": "Faster?",
                        "answer": "{g}",
                        "evidence": [
                            {
                                "kind": "value",
                                "path": "results/r.json",
                                "key": "gain",
                                "name": "g",
                            }
                        ],
                    },
                ],
            },
            f,
        )
    with open("main.md", "w") as f:
        f.write(
            "<!-- calkit values path=results/r.json -->\n"
            "It's <!-- calkit value key=gain -->1.0<!-- /calkit value -->x"
            " faster.\n"
        )
    with open("template.tex", "w") as f:
        f.write("$body$\nBuilt by $calkit-version$ from $project$.\n")
    os.makedirs("img")
    with open("img/p.png", "wb") as f:
        f.write(b"")
    with open("main.md", "a") as f:
        f.write("\n![A plot](img/p.png)\n")
    # Both LaTeX, with images pointed at from where it's written, and a
    # second copy of it
    subprocess.check_call(
        [
            "calkit",
            "latex",
            "from-markdown",
            os.path.abspath("main.md"),
            "-o",
            "build/main.tex",
            "-o",
            "other/main.tex",
            "--template",
            "template.tex",
        ]
    )
    assert "{../img/p.png}" in open("other/main.tex").read()
    tex = open("build/main.tex").read()
    # The value is current and links to the question citing it, not just
    # the first to cite its file
    assert r"\href{https://calkit.io/someone/proj/questions/2}{2.0}" in tex
    assert "from calkit.io/someone/proj." in tex
    assert "Built by " + calkit.__version__.split("+")[0] in tex
    # The Markdown itself is kept current too
    assert "-->2.0<!--" in open("main.md").read()
    # Only PDFs and LaTeX can be written
    result = subprocess.run(
        ["calkit", "latex", "from-markdown", "main.md", "-o", "main.html"],
        capture_output=True,
    )
    assert result.returncode != 0
    # Nor from outside the project
    result = subprocess.run(
        ["calkit", "latex", "from-markdown", "../x.md", "-o", "x.pdf"],
        capture_output=True,
        text=True,
    )
    assert "isn't in this project" in result.stderr + result.stdout
