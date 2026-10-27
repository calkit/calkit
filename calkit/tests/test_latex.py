"""Tests for ``calkit.latex``."""

import gzip
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import calkit.latex


def test_set_content_id(tmp_dir):
    import hashlib
    import re

    def pdf(section: bytes) -> bytes:
        # Just enough of a file for the trailer to be found, its
        # cross-reference section last and pointed to by startxref
        body = b"%PDF-1.5\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        return (
            body + section + b"startxref\n" + str(len(body)).encode() + b"\n"
            b"%%EOF\n"
        )

    table = (
        b"xref\n0 2\n0000000000 65535 f \n0000000009 00000 n \n"
        b"trailer\n<< /Size 2 /Root 1 0 R >>\n"
    )
    # A cross-reference stream whose data happens to hold '/ID'
    stream = (
        b"2 0 obj\n<< /Type /XRef /Size 3 /Length 4 >>\nstream\n/ID \n"
        b"endstream\nendobj\n"
    )
    for section in [table, stream]:
        data = pdf(section)
        Path("main.pdf").write_bytes(data)
        assert calkit.latex.set_content_id("main.pdf")
        out = Path("main.pdf").read_bytes()
        digest = hashlib.md5(data).hexdigest().upper()
        assert f"<< /ID [<{digest}> <{digest}>]".encode() in out
        # Inside the last section's dictionary, which every offset precedes
        m = re.search(rb"startxref\n(\d+)", out)
        assert m is not None
        assert out[int(m.group(1)) :].startswith(section[:6])
        assert out.index(b"/ID") > int(m.group(1))
        # An ID is left alone, so a second pass changes nothing
        assert not calkit.latex.set_content_id("main.pdf")
        assert Path("main.pdf").read_bytes() == out
    # A file that isn't a PDF is left alone
    Path("main.pdf").write_bytes(b"not a PDF")
    assert not calkit.latex.set_content_id("main.pdf")


def test_localize_synctex(tmp_dir):
    # Nothing to localize is not an error
    assert (
        calkit.latex.localize_synctex("paper/main.synctex.gz", "paper")
        is False
    )
    os.makedirs("paper")
    # Both exist, and the relative input is the paper's own
    for path in ("paper/main.tex", "paper/section.tex", "section.tex"):
        with open(path, "w") as f:
            f.write("\\documentclass{article}\n")
    with gzip.open("paper/main.synctex.gz", "wt") as f:
        f.write(
            "SyncTeX Version:1\n"
            "Input:1:/work/paper/./main.tex\n"
            "Input:2:/usr/local/texlive/2025/tex/latex/base/article.cls\n"
            "Input:3:./section.tex\n"
            "Content:\n"
        )
    assert (
        calkit.latex.localize_synctex("paper/main.synctex.gz", "paper") is True
    )
    with gzip.open("paper/main.synctex.gz", "rt") as f:
        text = f.read()
    here = Path(".").resolve()
    assert f"Input:1:{(here / 'paper/main.tex').as_posix()}" in text
    assert f"Input:3:{(here / 'paper/section.tex').as_posix()}" in text
    # A file the project doesn't have is left alone
    assert "Input:2:/usr/local/texlive/2025/tex/latex/base/article.cls" in text
    # Already local
    assert (
        calkit.latex.localize_synctex("paper/main.synctex.gz", "paper")
        is False
    )


def test_ck_components(tmp_dir):
    with open("calkit.yaml", "w") as f:
        f.write("name: test\n")
    os.makedirs("results")
    with open("results/metrics.json", "w") as f:
        json.dump(
            {"rmse": 0.123456, "n_runs": 42, "fit": {"slope": 1.2345}}, f
        )
    os.makedirs("figures")
    with open("figures/plot.png", "wb") as f:
        f.write(b"png")
    os.makedirs("tables")
    with open("tables/summary.tex", "w") as f:
        f.write("\\begin{tabular}{l}\\end{tabular}\n")
    os.makedirs("paper/sections")
    with open("paper/sections/results.tex", "w") as f:
        f.write("Error: \\ckvalue[.2f]{results/metrics.json}{rmse}.\n")
    with open("paper/main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n"
            "\\usepackage{calkit}\n"
            "\\begin{document}\n"
            "\\input{sections/results}\n"
            "\\ckfigure[width=0.5\\textwidth]{figures/plot.png}\n"
            "\\cktable{tables/summary.tex}\n"
            "Slope: \\ckvalue{results/metrics.json}{fit.slope},\n"
            "runs: \\ckvalue{results/metrics.json}{n_runs}.\n"
            "% \\ckfigure{figures/commented.png}\n"
            "\\ckvalue{results/metrics.json}{nope}\n"
            "\\ckfigure{figures/not-yet.png}\n"
            "\\end{document}\n"
        )
    # Inputs count, comments don't, and nothing repeats
    loads, components = calkit.latex.read_ck_usage("paper/main.tex")
    assert loads
    assert [(c.kind, c.path, c.key, c.format) for c in components] == [
        ("value", "results/metrics.json", "rmse", ".2f"),
        ("figure", "figures/plot.png", None, ""),
        ("table", "tables/summary.tex", None, ""),
        ("value", "results/metrics.json", "fit.slope", ""),
        ("value", "results/metrics.json", "n_runs", ""),
        ("value", "results/metrics.json", "nope", ""),
        ("figure", "figures/not-yet.png", None, ""),
    ]
    # An input isn't a document of its own
    docs = calkit.latex.root_documents("paper")
    assert [Path(d).as_posix() for d in docs] == ["paper/main.tex"]
    problems = calkit.latex.map_ck_components("paper")
    assert len(problems) == 2
    assert "results/metrics.json has no nope" in problems
    assert any("figures/not-yet.png" in p for p in problems)
    with open("paper/_calkit/figures/plot.png", "rb") as f:
        assert f.read() == b"png"
    assert os.path.isfile("paper/_calkit/tables/summary.tex")
    with open("paper/_calkit/values.tex") as f:
        values = f.read()
    # Numbers are written in full, since calkit.sty formats them, so a format
    # can change without anything being brought in again
    assert "\\cksetvalue{results/metrics.json}{rmse}{n}{0.123456}" in values
    assert "\\cksetvalue{results/metrics.json}{fit.slope}{n}{1.2345}" in values
    assert "\\cksetvalue{results/metrics.json}{n_runs}{n}{42}" in values
    assert ".2f" not in values
    # Where TeX finds a file is only written for one named without an
    # extension
    assert "cksetfile" not in values
    # Text is escaped, and only numbers are formatted
    assert calkit.latex.tex_value("run_a") == ("t", "run\\_a")
    assert calkit.latex.tex_value(True) == ("t", "True")
    assert calkit.latex.tex_value(float("nan")) == ("t", "nan")
    assert calkit.latex.tex_value([3]) == ("n", "3")
    assert calkit.latex.tex_value(1e-05) == ("n", "1e-05")
    # Kept out of Git without touching the project's own .gitignore
    with open("paper/_calkit/.gitignore") as f:
        assert f.read().strip().endswith("*")
    # And says not to edit it, which is all Overleaf shows
    with open("paper/_calkit/README.md") as f:
        assert "Don't edit" in f.read()
    assert os.path.isfile("paper/calkit.sty")
    # Unchanged content isn't rewritten, so latexmk has nothing to redo
    mtime = os.stat("paper/_calkit/values.tex").st_mtime_ns
    calkit.latex.map_ck_components("paper")
    assert os.stat("paper/_calkit/values.tex").st_mtime_ns == mtime
    # What's no longer included is removed, along with its emptied folder
    with open("paper/main.tex") as f:
        main = f.read()
    with open("paper/main.tex", "w") as f:
        f.write(main.replace("\\cktable{tables/summary.tex}\n", ""))
    calkit.latex.map_ck_components("paper")
    assert not os.path.exists("paper/_calkit/tables")
    assert os.path.isfile("paper/_calkit/figures/plot.png")
    # A document that doesn't load calkit.sty gets nothing, since its
    # commands couldn't compile
    os.makedirs("other")
    with open("other/main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n"
            "\\usepackage{amsmath}\n"
            "\\ckvalue{results/metrics.json}{rmse}\n"
        )
    assert calkit.latex.read_ck_usage("other/main.tex") == (False, [])
    assert calkit.latex.map_ck_components("other") == []
    assert os.listdir("other") == ["main.tex"]
    # One that does gets it before including anything, so it compiles, e.g.,
    # after loading it on Overleaf, including from a list of packages
    with open("other/main.tex", "w") as f:
        f.write("\\documentclass{article}\n\\usepackage{amsmath, calkit}\n")
    assert calkit.latex.map_ck_components("other") == []
    assert os.path.isfile("other/calkit.sty")
    assert os.path.isfile("other/_calkit/values.tex")
    # A folder with no documents gets nothing
    os.makedirs("figures-only")
    assert calkit.latex.map_ck_components("figures-only") == []
    assert os.listdir("figures-only") == []

    # Nothing outside the project is read, however it's named, and a figure
    # or table can be named without its extension, the way TeX finds it
    def component_path(path: str, kind: str = "value") -> tuple:
        return calkit.latex.component_path(
            calkit.latex.CkComponent(kind, path),
            lambda rel: (
                rel
                in {
                    "figures/plot.png",
                    "figures/fit_1.5.pdf",
                    "tables/summary.tex",
                    "results/m.json",
                }
            ),
        )

    assert component_path("../secret.json") == (
        None,
        "../secret.json is outside the project",
    )
    assert component_path("/etc/secret.json")[0] is None
    assert component_path("C:\\secret.json")[0] is None
    assert component_path("results/../results/m.json") == (
        None,
        "results/../results/m.json can't include '..'",
    )
    assert component_path("figures/plot", "figure") == (
        "figures/plot.png",
        None,
    )
    assert component_path("tables/summary", "table") == (
        "tables/summary.tex",
        None,
    )
    assert component_path("results/m")[0] is None
    # A dot in a name isn't taken for an extension
    assert component_path("figures/fit_1.5", "figure")[0] == (
        "figures/fit_1.5.pdf"
    )
    # The same can be worked out without the files on disk, e.g., from the
    # hub's copy of a repo, with figures stored with DVC fetched by name
    plan = calkit.latex.plan_ck_components(
        [
            calkit.latex.CkComponent("figure", "figures/plot"),
            calkit.latex.CkComponent("value", "results/m.json", "x"),
            calkit.latex.CkComponent("table", "README.md"),
        ],
        is_file=lambda rel: (
            rel in {"figures/plot.png", "results/m.json", "README.md"}
        ),
        read_data=lambda rel: {"x": 2},
    )
    assert plan.files == {"figures/plot.png": True}
    assert "\\cksetfile{figures/plot}{figures/plot.png}" in plan.values
    assert "\\cksetvalue{results/m.json}{x}{n}{2}" in plan.values
    assert plan.problems == ["README.md has a name Calkit uses in _calkit"]
    # Nothing is read through a link out of the project, e.g., one committed
    # to Git, though one within it is fine, as is one into DVC's cache,
    # wherever that's kept, and a name Calkit uses in _calkit can't be
    # included
    if sys.platform != "win32":
        outside = tempfile.mkdtemp()
        with open(os.path.join(outside, "secret.json"), "w") as f:
            f.write('{"key": "hunter2"}')
        cache = tempfile.mkdtemp()
        with open(os.path.join(cache, "cached.png"), "wb") as fb:
            fb.write(b"cached")
        os.makedirs(".dvc", exist_ok=True)
        with open(".dvc/config", "w") as f:
            f.write(f"[cache]\n    dir = {cache}\n")
        os.symlink(os.path.join(outside, "secret.json"), "results/secret.json")
        os.symlink(os.path.abspath("figures/plot.png"), "figures/inside.png")
        os.symlink(os.path.join(cache, "cached.png"), "figures/cached.png")
        with open("values.tex", "w") as f:
            f.write("A table")
        os.makedirs("linked")
        with open("linked/main.tex", "w") as f:
            f.write(
                "\\documentclass{article}\n\\usepackage{calkit}\n"
                "\\ckvalue{results/secret.json}{key}\n"
                "\\ckfigure{figures/inside.png}\n"
                "\\ckfigure{figures/cached.png}\n"
                "\\cktable{values.tex}\n"
            )
        problems = calkit.latex.map_ck_components("linked")
        assert "results/secret.json links outside the project" in problems
        assert "values.tex has a name Calkit uses in _calkit" in problems
        with open("linked/_calkit/values.tex") as f:
            assert "hunter2" not in f.read()
        with open("linked/_calkit/figures/cached.png", "rb") as fb:
            assert fb.read() == b"cached"
        assert os.path.isfile("linked/_calkit/figures/inside.png")
        # Nor is anything written, changed, or removed through a link, e.g.,
        # _calkit, or a folder in it
        shutil.rmtree("linked/_calkit")
        os.symlink(outside, "linked/_calkit")
        assert calkit.latex.map_ck_components("linked") == [
            os.path.join("linked", "_calkit")
            + " is a link, so Calkit won't write there"
        ]
        assert os.listdir(outside) == ["secret.json"]
        os.remove("linked/_calkit")
        os.makedirs("linked/_calkit")
        os.symlink(outside, "linked/_calkit/figures")
        problems = calkit.latex.map_ck_components("linked")
        assert "figures/inside.png would be copied through a link" in problems
        assert os.listdir(outside) == ["secret.json"]
    # Every document in a folder is mapped together, including one named
    # because its \documentclass is in a file it inputs, and an input's
    # inputs are read from where TeX compiles
    os.makedirs("more/front")
    with open("more/front/preamble.tex", "w") as f:
        f.write("\\documentclass{article}\n\\usepackage[final]{calkit}\n")
    with open("more/a.tex", "w") as f:
        f.write("\\input{front/preamble}\n\\ckfigure{figures/plot}\n")
    with open("more/b.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n"
            "\\RequirePackage{calkit}\n"
            "\\ckvalue{../outside.json}{secret}\n"
            "\\ckvalue{/etc/outside.json}{secret}\n"
            "\\ckvalue{results/metrics.json}{rmse}\n"
            "\\input{front/nested}\n"
        )
    with open("more/front/nested.tex", "w") as f:
        f.write("\\input{front/deeper}\n")
    with open("more/front/deeper.tex", "w") as f:
        f.write("\\cktable{tables/summary}\n")
    problems = calkit.latex.map_ck_components("more/a.tex")
    assert "../outside.json is outside the project" in problems
    assert "/etc/outside.json is outside the project" in problems
    assert os.path.isfile("more/_calkit/figures/plot.png")
    assert os.path.isfile("more/_calkit/tables/summary.tex")
    with open("more/_calkit/values.tex") as f:
        values = f.read()
    assert "secret" not in values
    assert "\\cksetfile{figures/plot}{figures/plot.png}" in values
    assert "\\cksetvalue{results/metrics.json}{rmse}{n}{0.123456}" in values
    # A read-only copy, e.g., of a file from DVC's cache, is still updated
    os.chmod("more/_calkit/figures/plot.png", 0o444)
    with open("figures/plot.png", "wb") as f:
        f.write(b"png, made again")
    calkit.latex.map_ck_components("more/a.tex")
    with open("more/_calkit/figures/plot.png", "rb") as f:
        assert f.read() == b"png, made again"
    # What's stored with DVC is only looked up for what isn't here, since
    # listing it is slow
    asked: list[str] = []
    calkit.latex.map_ck_components(
        "more/a.tex",
        is_tracked=lambda rel: bool(asked.append(rel)),
    )
    assert asked == []
    # One stored with DVC but not pulled, e.g., on the hub, is still found
    # where it would be, and a copy already there is kept
    os.remove("tables/summary.tex")
    calkit.latex.map_ck_components(
        "more/a.tex",
        is_tracked=lambda rel: rel == "tables/summary.tex",
    )
    with open("more/_calkit/values.tex") as f:
        assert "\\cksetfile{tables/summary}{tables/summary.tex}" in f.read()
    assert os.path.isfile("more/_calkit/tables/summary.tex")
    # A value whose file isn't pulled is kept from the values given, e.g.,
    # Overleaf's, or else the ones being replaced
    os.rename("results/metrics.json", "metrics.json.bak")

    def is_tracked(rel: str) -> bool:
        return rel in {"tables/summary.tex", "results/metrics.json"}

    for previous in [
        "\\cksetvalue{results/metrics.json}{rmse}{n}{0.5}\n",
        None,
    ]:
        problems = calkit.latex.map_ck_components(
            "more/a.tex",
            is_tracked=is_tracked,
            previous_values=previous,
        )
        assert not any("metrics" in p for p in problems)
        with open("more/_calkit/values.tex") as f:
            assert "{results/metrics.json}{rmse}{n}{0.5}" in f.read()
    problems = calkit.latex.map_ck_components(
        "more/a.tex",
        is_tracked=is_tracked,
        previous_values="",
    )
    assert "results/metrics.json is stored with DVC and not pulled" in problems
    os.rename("metrics.json.bak", "results/metrics.json")
    problems = calkit.latex.map_ck_components("more/a.tex")
    assert "tables/summary is not in the project yet" in problems
    with open("more/_calkit/values.tex") as f:
        assert "tables/summary" not in f.read()
    # Once no document loads calkit.sty, the folder goes, and so does
    # calkit.sty, since Calkit wrote it
    os.chmod("more/_calkit/figures/plot.png", 0o444)
    for name in ["a", "b"]:
        with open(f"more/{name}.tex", "w") as f:
            f.write("\\documentclass{article}\n")
    assert calkit.latex.map_ck_components("more") == []
    assert not os.path.exists("more/_calkit")
    assert not os.path.exists("more/calkit.sty")
    # But not one of the user's own
    with open("more/calkit.sty", "w") as f:
        f.write("\\ProvidesPackage{calkit}\n")
    calkit.latex.map_ck_components("more")
    assert os.path.isfile("more/calkit.sty")


def test_expand_ck_components(tmp_dir):
    # A revision's data, apart from its sources, as for the working tree's
    # side of a diff
    os.makedirs("data/results")
    with open("data/results/m.json", "w") as f:
        f.write('{"rmse": 0.456, "label": "run_b"}')
    os.makedirs("data/tables")
    with open("data/tables/t.tex", "w") as f:
        f.write("\\begin{tabular}{l}B\\end{tabular}")
    os.makedirs("data/figures")
    with open("data/figures/plot.png", "wb") as fb:
        fb.write(b"png")
    os.makedirs("src/paper")
    with open("src/paper/main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n"
            "Error: \\ckvalue[.2f]{results/m.json}{rmse}.\n"
            "Run: \\ckvalue{results/m.json}{label}.\n"
            "\\ckfigure[width=1cm]{figures/plot}\n"
            "\\ckfigure{figures/plot} {\\small (a) left}\n"
            "\\cktable{tables/t}\n"
            "Split: \\ckvalue{results/m.json}\n  {rmse}.\n"
            "Missing: \\ckvalue{results/m.json}{nope}.\n"
            "% \\ckvalue{results/m.json}{rmse}\n"
        )
    calkit.latex.expand_ck_components("src", "data", "paper/main.tex")
    with open("src/paper/main.tex") as f:
        text = f.read()
    # Each command becomes what it shows, so latexdiff can mark a change,
    # with numbers still formatted by calkit.sty
    assert "Error: \\cknum[.2f]{0.456}." in text
    # Including one split across lines
    assert "Split: \\cknum[]{0.456}." in text
    assert "Run: run\\_b." in text
    assert "\\includegraphics[width=1cm]{../figures/plot.png}" in text
    # A brace group after a figure isn't taken for an argument
    assert (
        "\\includegraphics[]{../figures/plot.png} {\\small (a) left}" in text
    )
    assert "\\begin{tabular}{l}B\\end{tabular}" in text
    # What can't be found is left to print as ??, and comments alone
    assert "\\ckvalue{results/m.json}{nope}" in text
    assert "% \\ckvalue{results/m.json}{rmse}" in text


def test_align_rendered_paragraphs() -> None:
    def at(start: str) -> int:
        return next(i + 1 for i, t in enumerate(src) if t.startswith(start))

    src = [
        r"\documentclass{article}",
        "",
        r"\newcommand{\tool}{Wake\textendash Sim\xspace}",
        "",
        r"\providecommand{\tool}{Other}",
        "",
        r"\newcommand{\scale}{1}",
        r"\renewcommand{\scale}{2}",
        "",
        r"\newcommand{\rate}[1]{#1 per second}",
        r"\newcommand{\aval}{\alpha}",
        r"\hypersetup{pdftitle={Wake recovery study}}",
        "",
        r"\title{Wake recovery study}",
        r"\begin{document}",
        r"\maketitle",
        r"\section{Methods}",
        r"\label{sec:methods}",
        r"We simulate the wake with \tool, which resolves 95\% of the "
        r"turbulent kinetic energy \citep{lee2018, park2016, smith2020}.",
        "",
        r"\begin{equation}",
        r"  L = a \text{ if } x < \tau, \text{ otherwise } b",
        r"\end{equation}",
        "",
        r"\begin{table}",
        r"\caption{Errors by method.}",
        r"\begin{tabular}{ll}",
        r"Model Type & \makecell{Time per\\molecule} \\",
        r"\end{tabular}",
        r"\end{table}",
        "",
        r"\subsection{Growth rate ($k=0.05$)}",
        "Errors are small for every model tested here.",
        "",
        "Training took longer for the largest model.",
        "",
        "Inference was fast for all models we compared.",
        "",
        r"\section{Appendix}",
        r"Unless otherwise stated, rates are \rate{3}.",
        r"\end{document}",
    ]
    lines = [
        calkit.latex.SourceLine("main.tex", i + 1, t)
        for i, t in enumerate(src)
    ]
    blks = calkit.latex.blocks(lines)
    by_line = {b.lineno: b for b in blks}
    # A heading is a block of its own with its label, macros without
    # arguments read as their text, an escaped percent sign doesn't start a
    # comment, and a line break doesn't run into the next word
    methods = at(r"\section{Methods}")
    assert [ln.lineno for ln in by_line[methods].lines] == [
        methods,
        methods + 1,
    ]
    prose = by_line[at("We simulate")].text
    assert prose == (
        "We simulate the wake with Wake–Sim, which resolves 95% of the "
        "turbulent kinetic energy ."
    )
    assert "Time per molecule" in by_line[at(r"\begin{tabular}")].text
    # A later definition wins, except by \providecommand, and expanding
    # keeps an empty group ending a command
    macros = blks[0].macros
    assert macros == {
        "tool": "Wake\\textendash Sim\\xspace",
        "scale": "2",
        "aval": "\\alpha",
    }
    assert (
        calkit.latex.expand_macros(r"$\aval{}x$", macros, math=True)
        == r"$\alpha{}x$"
    )
    texts = [
        # The title, though it's set in the preamble, which counts for
        # nothing else
        "Wake recovery study",
        "1. Methods",
        "We simulate the wake with Wake–Sim, which resolves 95% of the "
        "turbulent kinetic energy (Lee, 2018; Park et al., 2016; Smith and "
        "Jones, 2020).",
        # Pieces of the display, numbered mid-line or sharing one word with
        # prose further on
        "L = a if x < τ (1) otherwise b",
        ", otherwise,",
        "Table 1: Errors by method.",
        "1.1. Growth rate (k=0.05)",
        "Errors are small for every model tested here.",
        "Training took longer for the largest model.",
        "Inference was fast for all models we compared.",
        "2. Appendix",
        "Unless otherwise stated, rates are 3 per second.",
    ]
    matched = calkit.latex.align(texts, blks)
    assert [b.lineno if b else None for b in matched] == [
        at(r"\title"),
        methods,
        at("We simulate"),
        None,
        None,
        at(r"\caption"),
        at(r"\subsection"),
        at("Errors"),
        at("Training"),
        at("Inference"),
        at(r"\section{Appendix}"),
        at("Unless"),
    ]
    assert calkit.latex.equation_fragment("f(")
    assert calkit.latex.equation_fragment(", (4)")
    assert not calkit.latex.equation_fragment(
        "Combining (A.5) and (A.6), we get:"
    )
    assert not calkit.latex.equation_fragment("Actuator disk model (k=0.04)")


def test_detex() -> None:
    macros = {"ppt": r"\text{\textperthousand}\xspace"}
    # Symbols print as themselves, a command word skipping the space after
    # it, and \xspace adding none before punctuation
    cases = {
        r"a 5\ppt shift and 2\ppt.": "a 5‰ shift and 2‰.",
        r"error (\ppt) of 3 \ppt": "error (‰) of 3 ‰",
        r"4\textperthousand of": "4‰of",
        r"95\% of \$5 \& more": "95% of $5 & more",
        r"Born--Oppenheimer, 1--2, and---so": "Born–Oppenheimer, 1–2, and—so",
        r"``quoted''": "“quoted”",
        # Chemistry, quantities, and styled text without spaces around it
        r"\ce{^{2}H}-labeled \ce{CO2}": "2H-labeled CO2",
        r"at \SI{20}{\kelvin}, \si{\milli\second}": "at 20 K, ms",
        r"\SIrange{10}{50}{\kelvin}": "10 K to 50 K",
        r"an \textit{ad}-hoc fit": "an ad-hoc fit",
        r"\emph{\textbf{bold}}-ish": "bold-ish",
        r"Schr\"odinger and Erd\H{o}s": "Schrödinger and Erdős",
        r"see \href{https://x.org}{the site}": "see the site",
    }
    for src, text in cases.items():
        assert (
            calkit.latex.detex(calkit.latex.expand_macros(src, macros)) == text
        )
    # References and citations, whose text isn't known, can be marked
    ref, cite = calkit.latex.REF_MARK, calkit.latex.CITE_MARK
    src = r"Eq.~\eqref{eq:a} in \ref{sec:b}, as before \citep[e.g.,][]{x}."
    assert calkit.latex.detex(src, marks=True) == (
        f"Eq. ({ref}) in {ref}, as before {cite}."
    )
    assert calkit.latex.detex(src) == "Eq. in , as before ."
    # Math reads with Greek letters and operator names as themselves
    assert calkit.latex.math_text(r"\mathbf{u}_\text{ref}") == "u ref"
    assert calkit.latex.math_text(r"\Delta\ln p + \hbar\omega_k") == (
        "Δ ln p + ℏω k"
    )
    assert calkit.latex.math_text(r"\lambda L_{\max}") == "λ L max"
