"""Tests for ``calkit.latex``."""

from __future__ import annotations

import os

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
    assert r"\ckartifact{../figures/plot.pdf}{plot}{abc}" in table
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
    assert sidecar["document"] == "paper/main.tex"
    by = {(i["kind"], i["path"]): i for i in sidecar["injections"]}
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
