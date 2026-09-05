"""Tests for ``calkit.latex``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_provenance(tmp_dir):
    import json
    import subprocess

    import calkit
    import calkit.latex
    from calkit.latex import (
        collect_provenance,
        escape_tex,
        keyed_command,
        questions_tex,
        write_provenance_tex,
    )

    assert escape_tex("a_b & 100%") == r"a\_b \& 100\%"
    tex = keyed_command("val", {"a": "1", "b": r"\ckvalue{b}{2}{f.json}{s}"})
    assert r"\newcommand\val[1][all]" in tex
    assert r"\pdfstrcmp{#1}{a}=0" in tex
    assert tex.count(r"\fi") == 3
    # A project with a figure stage, a results stage and two questions
    subprocess.check_call(["git", "init", "-q"])
    os.makedirs("results")
    os.makedirs("figures")
    os.makedirs("paper")
    with open("results/findings.json", "w") as f:
        json.dump({"ratio": 5.1014, "name": "k_omega"}, f)
    with open("figures/plot.pdf", "w") as f:
        f.write("pdf")
    ck_info = {
        "pipeline": {
            "stages": {
                "plot": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "plot.py",
                    "inputs": ["results/findings.json"],
                    "outputs": ["figures/plot.pdf"],
                },
                "summarize": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "s.py",
                    "outputs": [{"path": "results/findings.json"}],
                },
            }
        },
        "questions": [
            "Plain?",
            {
                "question": "Does it work?",
                "hypothesis": "Yes.",
                "answer": "By {ratio:.1f}x, with {name} & 100% certainty.",
                "notes": "See {ratio}.",
                "evidence": [
                    {
                        "kind": "value",
                        "path": "results/findings.json",
                        "key": "ratio",
                    },
                    {
                        "kind": "value",
                        "path": "results/findings.json",
                        "key": "name",
                        "explanation": "The model is {name}.",
                    },
                    {"kind": "figure", "path": "figures/plot.pdf"},
                    {
                        "kind": "publication",
                        "path": "paper/main.pdf",
                        "section": "Results",
                        "label": "sec:results",
                    },
                ],
            },
        ],
    }
    with open("dvc.lock", "w") as f:
        f.write(
            "stages:\n  plot:\n    outs:\n    - path: figures/plot.pdf\n"
            "      md5: abc\n"
        )
    # Questions render placeholders as provenance-marked values, escape
    # TeX specials, and reference publication labels
    tex = questions_tex(ck_info, ".")
    assert r"\ckvalue{ratio}{5.1}{results/findings.json}{summarize}" in tex
    assert r"\ckvalue{name}{k\_omega}{results/findings.json}{summarize}" in tex
    assert r"\& 100\% certainty" in tex
    assert r"\ckvalue{ratio}{5.1014}{results/findings.json}{summarize}" in tex
    assert r"Section~\ref{sec:results} (Results)" in tex
    assert r"The model is \ckvalue{name}" in tex
    assert r"\newcommand\ckfindings{" in tex
    assert r"\textbf{Q2. \ckquestion[2]}" in tex
    assert r"\ckquestion[1]" not in tex.split(r"\newcommand\ckfindings")[1]
    ck_info["questions"][1]["answer"] = "{nope}"
    with pytest.raises(KeyError):
        questions_tex(ck_info, ".")
    ck_info["questions"][1]["answer"] = "fine"
    # The artifact table names the stage behind each referenced file, as
    # the document writes the path
    with open("paper/main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\\usepackage[provenance]{calkit}\n"
            "\\begin{document}\\ckfigure[width=1in]{../figures/plot.pdf}"
            "\\input{generated-numbers}\\end{document}\n"
        )
    with open("paper/generated-numbers.tex", "w") as f:
        f.write("")
    write_provenance_tex("paper/main.tex", ck_info, ".")
    with open("paper/calkit-provenance.tex") as f:
        table = f.read()
    assert (
        r"\ckartifact{../figures/plot.pdf}{plot}{abc}{figures/plot.pdf}"
        in table
    )
    assert calkit.latex.detect_inputs("paper/main.tex", ".") == [
        "figures/plot.pdf",
        "paper/generated-numbers.tex",
    ]
    # The style is installed beside the document, then left alone
    dest = calkit.latex.install_style("paper/main.tex", ".")
    assert os.path.isfile(dest)
    with open(dest) as f:
        assert r"\ProvidesPackage{calkit}" in f.read()
    # A build log becomes the sidecar, resolved against the project
    with open("paper/main.ckprov", "w") as f:
        f.write(
            '{"kind": "figure", "path": "../figures/plot.pdf", "key": "", '
            '"page": 1}\n'
            '{"kind": "value", "path": "results/findings.json", '
            '"key": "ratio", "page": 2}\n'
            '{"kind": "value", "path": "results/findings.json", '
            '"key": "ratio", "page": 3}\n'
        )
    sidecar = collect_provenance("paper/main.tex", ck_info, ".")
    # The artifact is what the build produced; the source is where a
    # person edits it, and only some kinds of artifact have one
    assert sidecar["artifact"] == "paper/main.pdf"
    assert sidecar["source"] == "paper/main.tex"
    assert sidecar["kind"] == "publication"
    assert sidecar["$schema"].endswith("/schemas/provenance.json")
    assert "falsifies" in sidecar["_note"]
    # The build log is scratch and does not survive the read
    assert not os.path.isfile("paper/main.ckprov")
    by = {(i["kind"], i["path"]): i for i in sidecar["components"]}
    fig = by[("figure", "figures/plot.pdf")]
    assert fig["stage"] == "plot"
    assert fig["hash"] == "abc"
    assert fig["stage_inputs"] == ["results/findings.json"]
    assert fig["pages"] == [1]
    # Value paths are written relative to the project by the generated
    # macros, so they resolve as given
    val = by[("value", "results/findings.json")]
    assert val["pages"] == [2, 3]
    assert os.path.isfile("paper/main.provenance.json")
    # The CLI command writes the questions file
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(
        ["calkit", "latex", "from-questions", "-o", "paper/gq.tex"]
    )
    with open("paper/gq.tex") as f:
        assert r"\newcommand\ckanswer" in f.read()


def test_synctex_places_a_float_where_it_landed(tmp_dir):
    # The reason to ask TeX rather than to guess from the source: a float
    # is typeset where it fits, not where it was written
    import gzip

    import calkit.latex as cl

    os.makedirs("paper")
    with gzip.open("paper/main.synctex.gz", "wt") as f:
        f.write(
            "SyncTeX Version:1\n"
            "Input:1:/work/paper/./main.tex\n"
            "Input:2:/usr/share/texmf/tex/latex/base/article.cls\n"
            "Content:\n"
            "{1\n"
            "[1,4:0,0\n"
            "]\n"
            "}1\n"
            "{2\n"
            "(1,7:0,0\n"
            ")\n"
            "}2\n"
        )
    mapping = cl.synctex_pages("paper/main.tex", ".")
    # Keyed by the path TeX recorded, which a container build makes
    # absolute and inside the container
    assert "/work/paper/main.tex" in mapping
    assert cl.pages_at(mapping, "paper/main.tex", 7) == [2]
    assert cl.pages_at(mapping, "paper/main.tex", 4) == [1]
    # A line TeX recorded nothing for belongs to the box that carried it,
    # which is the nearest line at or before it
    assert cl.pages_at(mapping, "paper/main.tex", 5) == [1]
    assert cl.pages_at(mapping, "paper/main.tex", 9) == [2]
    # Nothing before the first record, and nothing for another file
    assert cl.pages_at(mapping, "paper/main.tex", 1) == []
    assert cl.pages_at(mapping, "paper/other.tex", 7) == []


def test_no_synctex_is_no_pages_rather_than_an_error(tmp_dir):
    import calkit.latex as cl

    assert cl.synctex_pages("paper/main.tex", ".") == {}
    assert cl.pages_at({}, "paper/main.tex", 1) == []


def test_provenance_without_anything_in_the_document(tmp_dir):
    # The point of the rework: a paper that uses plain LaTeX gets a record
    # like any other. No \usepackage{calkit}, no \ckfigure, no build log.
    import gzip
    import json
    import subprocess

    from calkit.latex import collect_provenance

    subprocess.check_call(["git", "init", "-q"])
    os.makedirs("figures")
    os.makedirs("results")
    os.makedirs("paper")
    with open("figures/plot.pdf", "w") as f:
        f.write("pdf")
    with open("results/findings.json", "w") as f:
        json.dump({"ratio": 5.1014}, f)
    ck_info = {
        "pipeline": {
            "stages": {
                "plot": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "plot.py",
                    "inputs": ["results/findings.json"],
                    "outputs": ["figures/plot.pdf"],
                }
            }
        }
    }
    with open("paper/main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n"
            "\\usepackage{graphicx}\n"
            "\\begin{document}\n"
            "\\includegraphics{../figures/plot.pdf}\n"
            "\\end{document}\n"
        )
    with gzip.open("paper/main.synctex.gz", "wt") as f:
        f.write(
            "SyncTeX Version:1\n"
            "Input:1:/work/paper/./main.tex\n"
            "Content:\n"
            "{3\n"
            "[1,4:0,0\n"
            "]\n"
            "}3\n"
        )
    sidecar = collect_provenance("paper/main.tex", ck_info, ".")
    assert len(sidecar["components"]) == 1
    figure = sidecar["components"][0]
    assert figure["kind"] == "figure"
    assert figure["path"] == "figures/plot.pdf"
    # The stage behind it, and the page TeX put it on
    assert figure["stage"] == "plot"
    assert figure["stage_inputs"] == ["results/findings.json"]
    assert figure["pages"] == [3]


def test_synctex_paths_are_pointed_at_the_files_that_exist(tmp_dir):
    # A container build records the container's paths. Reverse search then
    # finds the right line of a file the editor cannot open, which reads
    # as the feature being broken rather than the path being someone
    # else's.
    import gzip

    import calkit.latex as cl

    os.makedirs("paper")
    with open("paper/main.tex", "w") as f:
        f.write("\\documentclass{article}\n")
    with gzip.open("paper/main.synctex.gz", "wt") as f:
        f.write(
            "SyncTeX Version:1\n"
            "Input:1:/work/paper/./main.tex\n"
            "Input:2:/usr/local/texlive/2025/tex/latex/base/article.cls\n"
            "Content:\n"
            "{1\n"
            "[1,1:0,0\n"
            "]\n"
            "}1\n"
        )
    assert cl.localize_synctex("paper/main.tex", ".") is True
    with gzip.open("paper/main.synctex.gz", "rt") as f:
        text = f.read()
    here = (Path(".").resolve() / "paper/main.tex").as_posix()
    assert f"Input:1:{here}" in text
    # A file the project does not have is somebody else's to resolve
    assert "Input:2:/usr/local/texlive/2025/tex/latex/base/article.cls" in text
    # Already local, so nothing to do and nothing rewritten
    assert cl.localize_synctex("paper/main.tex", ".") is False
    # Still readable for pages afterwards
    assert cl.pages_at(
        cl.synctex_pages("paper/main.tex", "."), "paper/main.tex", 1
    ) == [1]


def test_localize_synctex_without_one_is_not_an_error(tmp_dir):
    import calkit.latex as cl

    assert cl.localize_synctex("paper/main.tex", ".") is False
