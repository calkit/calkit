"""Tests for ``calkit.components``."""

from __future__ import annotations

import json
import os
import subprocess


def _project() -> dict:
    """A project whose paper injects two values, a figure and a question."""
    subprocess.check_call(["git", "init", "-q"])
    os.makedirs("results")
    os.makedirs("figures")
    os.makedirs("paper")
    with open("results/findings.json", "w") as f:
        json.dump({"ratio": 5.1014, "name": "k_omega"}, f)
    with open("figures/plot.pdf", "w") as f:
        f.write("pdf")
    for script in ("plot.py", "s.py"):
        with open(script, "w") as f:
            f.write("print(1)\n")
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
            {
                "question": "Does it work?",
                "answer": "By {ratio:.1f}x with {name}.",
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
                    },
                ],
            }
        ],
    }
    with open("dvc.lock", "w") as f:
        f.write(
            "stages:\n  plot:\n    outs:\n    - path: figures/plot.pdf\n"
            "      md5: abc\n"
        )
    with open("paper/main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n"
            "\\usepackage[provenance]{calkit}\n"
            "\\input{generated-numbers}\n"
            "\\input{gq}\n"
            "\\begin{document}\n"
            "Ratio \\result[ratio] for \\result[name].\n"
            "\\ckfigure[width=1in]{../figures/plot.pdf}\n"
            "\\ckfindings\n"
            "\\end{document}\n"
        )
    return ck_info


def _generate(ck_info: dict) -> None:
    import calkit
    import calkit.latex

    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(
        [
            "calkit",
            "latex",
            "from-json",
            "results/findings.json",
            "-o",
            "paper/generated-numbers.tex",
            "--command",
            "result",
        ]
    )
    subprocess.check_call(
        ["calkit", "latex", "from-questions", "-o", "paper/gq.tex"]
    )


def test_describe_document_unbuilt(tmp_dir):
    import calkit.components as cc

    ck_info = _project()
    _generate(ck_info)
    doc = cc.describe_document("paper/main.tex", check_stages=False)
    assert not doc.built
    by = {(c.kind, c.location): c for c in doc.components}
    # Each value knows the file, the stage, and the script to open to
    # change it
    ratio = by[("value", "results/findings.json:ratio")]
    assert ratio.stage == "summarize"
    assert ratio.script == "s.py"
    assert ratio.current_value == 5.1014
    fig = by[("figure", "figures/plot.pdf")]
    assert fig.stage == "plot"
    assert fig.script == "plot.py"
    assert fig.stage_inputs == ["results/findings.json"]
    # The question block is a component of its own
    assert ("block", "calkit.yaml:1") in by
    # Pulling in a generated file is the mechanism, not a component
    assert not [c for c in doc.components if c.path.endswith("gq.tex")]
    # A generated file defines every value in its results file; only the
    # ones the document actually cites are components of the document
    with open("results/findings.json", "w") as f:
        json.dump({"ratio": 5.1014, "name": "k_omega", "unused": 1}, f)
    _generate(ck_info)
    doc = cc.describe_document("paper/main.tex", check_stages=False)
    assert sorted(c.key for c in doc.components if c.kind == "value") == [
        "name",
        "ratio",
    ]
    # Nothing was built and no stage status was asked for, so nothing can
    # honestly be called current -- except the question block, whose
    # currency is a question calkit.questions answers on its own
    assert {c.status for c in doc.components if c.kind != "block"} == {
        "unknown"
    }
    assert by[("block", "calkit.yaml:1")].status in ("ok", "stale")


def test_resolve_position(tmp_dir):
    import calkit.components as cc

    ck_info = _project()
    _generate(ck_info)
    line = 6  # Ratio \result[ratio] for \result[name].
    both = cc.resolve_position("paper/main.tex", line, check_stages=False)
    assert [c.key for c in both] == ["ratio", "name"]
    # A column picks out the one under the cursor, and the value shown is
    # the one as the document typesets it
    at_ratio = cc.resolve_position(
        "paper/main.tex", line, col=10, check_stages=False
    )
    assert [c.key for c in at_ratio] == ["ratio"]
    assert at_ratio[0].document_value == "5.1014"
    # A figure resolves through the document-relative path it is written as
    fig = cc.resolve_position("paper/main.tex", 7, check_stages=False)
    assert [(c.kind, c.path) for c in fig] == [("figure", "figures/plot.pdf")]
    # \ckfindings expands to the block and the values inside the answer,
    # with the answer's own formatting
    findings = cc.resolve_position("paper/main.tex", 8, check_stages=False)
    assert [c.kind for c in findings] == ["block", "value", "value"]
    assert [c.document_value for c in findings[1:]] == ["5.1", "k_omega"]
    # Nothing on a line with no injections, and nothing off the end
    assert cc.resolve_position("paper/main.tex", 1, check_stages=False) == []
    assert cc.resolve_position("paper/main.tex", 99, check_stages=False) == []


def test_staleness_after_build(tmp_dir):
    import calkit.components as cc
    import calkit.latex

    ck_info = _project()
    _generate(ck_info)
    with open("paper/main.ckprov", "w") as f:
        f.write(
            '{"kind": "value", "path": "results/findings.json", '
            '"key": "ratio", "page": 1}\n'
            '{"kind": "value", "path": "results/findings.json", '
            '"key": "ratio", "page": 3}\n'
            '{"kind": "value", "path": "results/findings.json", '
            '"key": "name", "page": 1}\n'
            '{"kind": "figure", "path": "../figures/plot.pdf", "key": "", '
            '"page": 2}\n'
        )
    sidecar = calkit.latex.collect_provenance("paper/main.tex", ck_info, ".")
    built = {(c["kind"], c["key"]): c for c in sidecar["components"]}
    # The build records the raw value it used, not the typeset text: one
    # value can appear formatted several ways in one document
    assert built[("value", "ratio")]["value"] == 5.1014
    assert built[("value", "ratio")]["pages"] == [1, 3]
    assert built[("figure", None)]["hash"] == "abc"
    doc = cc.describe_document("paper/main.pdf", check_stages=False)
    assert doc.built
    assert doc.needs_attention == []
    # A rerun moves one value on; the other, and the figure, are untouched
    with open("results/findings.json", "w") as f:
        json.dump({"ratio": 7.9, "name": "k_omega"}, f)
    doc = cc.describe_document("paper/main.pdf", check_stages=False)
    by = {c.location: c for c in doc.components}
    ratio = by["results/findings.json:ratio"]
    assert ratio.status == "stale"
    assert ratio.stale_reasons == ["changed-since-build"]
    assert (ratio.build_value, ratio.current_value) == (5.1014, 7.9)
    assert by["results/findings.json:name"].status == "ok"
    assert by["figures/plot.pdf"].status == "ok"
    assert [c.location for c in doc.needs_attention] == [
        "results/findings.json:ratio"
    ]
    # The figure the pipeline recorded differently is stale on its hash
    with open("dvc.lock", "w") as f:
        f.write(
            "stages:\n  plot:\n    outs:\n    - path: figures/plot.pdf\n"
            "      md5: def\n"
        )
    doc = cc.describe_document("paper/main.pdf", check_stages=False)
    fig = {c.location: c for c in doc.components}["figures/plot.pdf"]
    assert fig.stale_reasons == ["changed-since-build"]
    # A file the project no longer has reads as missing, not as current
    os.remove("figures/plot.pdf")
    doc = cc.describe_document("paper/main.pdf", check_stages=False)
    assert {c.location: c for c in doc.components}[
        "figures/plot.pdf"
    ].status == "missing"


def test_source_locations(tmp_dir):
    import calkit.components as cc

    ck_info = _project()
    _generate(ck_info)
    doc = cc.describe_document("paper/main.tex", check_stages=False)
    by = {c.location: c for c in doc.components}
    # An editor needs the line to put a marker on, and a value cited twice
    # is written in two places
    ratio = by["results/findings.json:ratio"]
    assert [(loc.source, loc.line) for loc in ratio.locations] == [
        ("paper/main.tex", 6),
        ("paper/main.tex", 8),
    ]
    # The column points at the command, so a cursor test can find it again
    line = open("paper/main.tex").read().splitlines()[5]
    column = ratio.locations[0].column
    assert line[column - 1 :].startswith("\\result[ratio]")
    assert (
        cc.resolve_position(
            "paper/main.tex", 6, col=column, check_stages=False
        )[0].key
        == "ratio"
    )
    assert [
        (loc.source, loc.line) for loc in by["figures/plot.pdf"].locations
    ] == [("paper/main.tex", 7)]
    # A document builds, then stops citing a value anywhere: the build
    # still shows it, and there is nowhere in the source left to point at
    with open("paper/main.ckprov", "w") as f:
        f.write(
            '{"kind": "value", "path": "results/findings.json", '
            '"key": "ratio", "page": 1}\n'
        )
    import calkit.latex

    calkit.latex.collect_provenance("paper/main.tex", ck_info, ".")
    with open("paper/main.tex") as f:
        tex = f.read()
    with open("paper/main.tex", "w") as f:
        f.write(
            tex.replace(
                "Ratio \\result[ratio] for \\result[name].", ""
            ).replace("\\ckfindings", "")
        )
    doc = cc.describe_document("paper/main.pdf", check_stages=False)
    assert doc.built
    assert {c.location: c for c in doc.components}[
        "results/findings.json:ratio"
    ].locations == []


def test_provenance_of_a_component(tmp_dir):
    import calkit.components as cc

    ck_info = _project()
    os.makedirs("img")
    for name in ("schematic.pdf", "rig.pdf", "published.pdf"):
        with open(os.path.join("img", name), "w") as f:
            f.write("pdf")
    ck_info["figures"] = [
        {"path": "img/rig.pdf", "created_by": {"email": "me@myorg.edu"}},
        {
            "path": "img/published.pdf",
            "imported_from": {"doi": "10.5281/zenodo.1234567"},
        },
    ]
    with open("paper/main.tex") as f:
        tex = f.read()
    with open("paper/main.tex", "w") as f:
        f.write(
            tex.replace(
                "\\ckfigure[width=1in]{../figures/plot.pdf}\n",
                "\\ckfigure[width=1in]{../figures/plot.pdf}\n"
                "\\ckfigure{../img/schematic.pdf}\n"
                "\\ckfigure{../img/rig.pdf}\n"
                "\\ckfigure{../img/published.pdf}\n",
            )
        )
    _generate(ck_info)
    doc = cc.describe_document("paper/main.tex", check_stages=False)
    by = {c.location: c for c in doc.components}
    # A stage that makes it is the end of the question
    assert by["figures/plot.pdf"].provenance == "pipeline"
    assert by["results/findings.json:ratio"].provenance == "pipeline"
    # Otherwise the file has to say for itself
    assert by["img/rig.pdf"].provenance == "attested"
    assert by["img/published.pdf"].provenance == "imported"
    # Nothing makes it and nobody claims it: the gap worth flagging
    assert by["img/schematic.pdf"].provenance == "undeclared"
    # The project's own words are not an outside source
    assert by["calkit.yaml:1"].provenance == "project"


def test_component_helpers(tmp_dir):
    import calkit.components as cc

    assert cc.source_path("paper/main.pdf") == "paper/main.tex"
    assert cc.source_path("paper/main.provenance.json") == "paper/main.tex"
    assert cc.source_path("paper/main.tex") == "paper/main.tex"
    # Values carry escaped TeX; components come back in plain terms
    found = cc.components_in_tex(
        r"\ckvalue{a\_b}{k\_omega}{results/f.json}{s}\ckblock{2}{calkit.yaml}"
    )
    assert found[0] == {
        "kind": "value",
        "path": "results/f.json",
        "key": "a_b",
        "document_value": "k_omega",
    }
    assert found[1] == {"kind": "block", "path": "calkit.yaml", "key": "2"}
    # A value containing braces is still read whole
    assert (
        cc.components_in_tex(r"\ckvalue{a}{x\textbackslash{}y}{f.json}{s}")[0][
            "document_value"
        ]
        == "x\\y"
    )
    assert cc.components_in_tex(r"\ckvalue{a}{1}") == []
