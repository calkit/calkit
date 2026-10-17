"""Tests for ``calkit.latex``."""

import gzip
import json
import os
from pathlib import Path

import calkit.latex


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


def test_cited_content(tmp_dir):
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
    citations = calkit.latex.find_citations("paper/main.tex")
    assert [(c.kind, c.path, c.key, c.format) for c in citations] == [
        ("value", "results/metrics.json", "rmse", ".2f"),
        ("figure", "figures/plot.png", None, ""),
        ("table", "tables/summary.tex", None, ""),
        ("value", "results/metrics.json", "fit.slope", ""),
        ("value", "results/metrics.json", "n_runs", ""),
        ("value", "results/metrics.json", "nope", ""),
        ("figure", "figures/not-yet.png", None, ""),
    ]
    # An input isn't a document of its own
    assert calkit.latex.root_documents("paper") == ["paper/main.tex"]
    problems = calkit.latex.write_cited("paper")
    assert len(problems) == 2
    assert any("nope" in p for p in problems)
    assert any("figures/not-yet.png" in p for p in problems)
    with open("paper/_calkit/figures/plot.png", "rb") as f:
        assert f.read() == b"png"
    assert os.path.isfile("paper/_calkit/tables/summary.tex")
    with open("paper/_calkit/values.tex") as f:
        values = f.read()
    assert "\\cksetvalue{results/metrics.json}{rmse}{.2f}{0.12}" in values
    assert "\\cksetvalue{results/metrics.json}{fit.slope}{}{1.2345}" in values
    assert "\\cksetvalue{results/metrics.json}{n_runs}{}{42}" in values
    # Kept out of Git without touching the project's own .gitignore
    with open("paper/_calkit/.gitignore") as f:
        assert f.read().strip().endswith("*")
    assert os.path.isfile("paper/calkit.sty")
    # Unchanged content isn't rewritten, so latexmk has nothing to redo
    mtime = os.stat("paper/_calkit/values.tex").st_mtime_ns
    calkit.latex.write_cited("paper")
    assert os.stat("paper/_calkit/values.tex").st_mtime_ns == mtime
    # What's no longer cited is removed, along with its emptied folder
    with open("paper/main.tex") as f:
        main = f.read()
    with open("paper/main.tex", "w") as f:
        f.write(main.replace("\\cktable{tables/summary.tex}\n", ""))
    calkit.latex.write_cited("paper")
    assert not os.path.exists("paper/_calkit/tables")
    assert os.path.isfile("paper/_calkit/figures/plot.png")
    # A folder whose documents cite nothing gets nothing
    os.makedirs("other")
    with open("other/main.tex", "w") as f:
        f.write("\\documentclass{article}\n")
    assert calkit.latex.write_cited("other") == []
    assert not os.path.exists("other/_calkit")
    assert not os.path.exists("other/calkit.sty")
