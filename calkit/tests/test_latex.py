"""Tests for ``calkit.latex``."""

import gzip
import json
import os
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
    components = calkit.latex.find_ck_components("paper/main.tex")
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
    # Text is escaped, and only numbers are formatted
    assert calkit.latex.tex_value("run_a") == ("t", "run\\_a")
    assert calkit.latex.tex_value(True) == ("t", "True")
    assert calkit.latex.tex_value(float("nan")) == ("t", "nan")
    assert calkit.latex.tex_value([3]) == ("n", "3")
    assert calkit.latex.tex_value(1e-05) == ("n", "1e-05")
    # Kept out of Git without touching the project's own .gitignore
    with open("paper/_calkit/.gitignore") as f:
        assert f.read().strip().endswith("*")
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
    # A folder whose documents cite nothing gets nothing
    os.makedirs("other")
    with open("other/main.tex", "w") as f:
        f.write("\\documentclass{article}\n")
    assert calkit.latex.map_ck_components("other") == []
    assert not os.path.exists("other/_calkit")
    assert not os.path.exists("other/calkit.sty")
    # Unless it's synced with Overleaf, where citing should compile before
    # the next sync brings anything in
    assert calkit.latex.map_ck_components("other", always=True) == []
    assert os.path.isfile("other/calkit.sty")
    assert os.path.isfile("other/_calkit/values.tex")
    # A folder with no documents gets nothing either way
    os.makedirs("figures-only")
    assert calkit.latex.map_ck_components("figures-only", always=True) == []
    assert os.listdir("figures-only") == []
