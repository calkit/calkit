"""Tests for ``calkit.quarto``."""

import json
import shutil
import subprocess

import pytest

import calkit.quarto
from calkit.markdown import MarkdownParseError
from calkit.results import VALUE_COMMANDS


@pytest.mark.parametrize("command", VALUE_COMMANDS)
def test_values(tmp_path, monkeypatch, command):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results.json").write_text(
        json.dumps({"rms": 0.123456, "fit": {"n": 401, "coeffs": [1.5, 2]}})
    )
    (tmp_path / "metrics.yaml").write_text("speed: 3.25\n")
    # A notebook's shortcodes are in its Markdown and raw cells, not its code
    nb = {
        "cells": [
            {"cell_type": "markdown", "source": ["The RMS is\n", "{{< "]},
            {"cell_type": "code", "source": "{{< ckvalue code.json x >}}"},
            {"cell_type": "raw", "source": "{{< ckvalue results.json rms >}}"},
        ]
    }
    (tmp_path / "doc.ipynb").write_text(
        json.dumps(nb).replace("ckvalue", command)
    )
    text = calkit.quarto.read_document_text("doc.ipynb")
    assert text == (
        "The RMS is\n{{< \n{{< ckvalue results.json rms >}}"
    ).replace("ckvalue", command)
    assert len(calkit.quarto.extract_values(text, "doc.ipynb")) == 1
    assert calkit.quarto.read_document_text("missing.qmd") is None
    # Arguments read like the Markdown marker's, positionally or by name,
    # with a declared result's name standing for its path
    text = (
        "RMS {{< ckvalue results.json rms .2f >}} over "
        "{{< ckvalue key=fit.n path=results.json >}} samples\n"
        "at {{< ckvalue speed key=speed format='{value:.1f} m/s' >}}; "
        "{{</* ckvalue escaped.json x */>}}\n"
        "{{< ckvalue results.json fit.coeffs.0 .1% >}}\n"
    ).replace("ckvalue", command)
    values = calkit.quarto.extract_values(
        text, "doc.qmd", results={"speed": "metrics.yaml"}
    )
    assert [(v.path, v.key, v.format, v.line) for v in values] == [
        ("results.json", "rms", ".2f", 1),
        ("results.json", "fit.n", None, 1),
        ("metrics.yaml", "speed", "{value:.1f} m/s", 2),
        ("results.json", "fit.coeffs.0", ".1%", 3),
    ]
    # Each is shown as Python formats it
    assert calkit.quarto.check_values(values, "doc.qmd") == [
        "0.12",
        "401",
        "3.2 m/s",
        "150.0%",
    ]
    # A notebook stands for the values its cells save
    fit_values = calkit.quarto.extract_values(
        f"{{{{< {command} nbs/fit.ipynb k_25 .3f >}}}}", "doc.qmd"
    )
    assert fit_values[0].path == (
        ".calkit/notebooks/outputs/nbs/fit.ipynb/values.json"
    )
    with pytest.raises(MarkdownParseError, match="No values saved from"):
        calkit.quarto.check_values(fit_values, "doc.qmd")
    (tmp_path / fit_values[0].path).parent.mkdir(parents=True)
    (tmp_path / fit_values[0].path).write_text(json.dumps({"k_25": 0.030912}))
    assert calkit.quarto.check_values(fit_values, "doc.qmd") == ["0.031"]
    # Mistakes name their line
    with pytest.raises(MarkdownParseError, match="names no key"):
        calkit.quarto.extract_values("\n{{< ckvalue a.json >}}", "doc.qmd")
    with pytest.raises(MarkdownParseError, match="doesn't exist"):
        calkit.quarto.check_values(
            calkit.quarto.extract_values(
                "{{< ckvalue gone.json x >}}", "doc.qmd"
            ),
            "doc.qmd",
        )
    with pytest.raises(MarkdownParseError, match="has no key 'nope'"):
        calkit.quarto.check_values(
            calkit.quarto.extract_values(
                "{{< ckvalue results.json nope >}}", "doc.qmd"
            ),
            "doc.qmd",
        )
    # As are what the shortcode can't read or format the way Python does,
    # including YAML text that Pandoc, which reads it, would change
    (tmp_path / "text.yaml").write_text(
        "version: '1.50'\nemphasis: a *b*\npath: 'C:\\data'\nname: run_a\n"
    )
    assert calkit.quarto.check_values(
        calkit.quarto.extract_values(
            "{{< ckvalue text.yaml name >}}", "doc.qmd"
        ),
        "doc.qmd",
    ) == ["run_a"]
    for text, match in [
        ("{{< ckvalue results.json rms ' .2f' >}}", "can't format"),
        ("{{< ckvalue results.json rms 8.2f >}}", "can't format"),
        ("{{< ckvalue results.json rms '{x:.2f}' >}}", "can't format"),
        ("{{< ckvalue results.json rms d >}}", "Can't format 'rms'"),
        ("{{< ckvalue results.json fit >}}", "list or table"),
        ("{{< ckvalue text.yaml version >}}", "looks like a number"),
        ("{{< ckvalue text.yaml emphasis >}}", "reads as Markdown"),
        ("{{< ckvalue text.yaml path >}}", "reads as Markdown"),
    ]:
        with pytest.raises(MarkdownParseError, match=match):
            calkit.quarto.check_values(
                calkit.quarto.extract_values(text, "doc.qmd"), "doc.qmd"
            )
    # Embedded documents are found relative to the document, or to its
    # Quarto project with a leading slash, which is its folder without one
    text = (
        "{{< embed ../analysis.ipynb#fig-decay >}}\n"
        '{{< embed "/analysis.ipynb#tbl-fit" >}}\n'
        "{{< embed notes.qmd >}} {{</* embed escaped.ipynb */>}}\n"
    )
    assert calkit.quarto.extract_embedded_paths(text, "pub/doc.qmd") == [
        "analysis.ipynb",
        "pub/analysis.ipynb",
        "pub/notes.qmd",
    ]
    # Without a Quarto project, the extension is written beside the
    # document, and left alone when already right
    (tmp_path / "pub").mkdir()
    calkit.quarto.write_components("pub/index.ipynb")
    ext = tmp_path / "pub" / "_extensions" / "calkit"
    assert (ext / "calkit.lua").read_text() == calkit.quarto.SHORTCODE_LUA
    assert "calkit.lua" in (ext / "_extension.yml").read_text()
    assert not (tmp_path / "pub" / "_calkit").exists()
    mtime = (ext / "calkit.lua").stat().st_mtime_ns
    calkit.quarto.write_components("pub/index.ipynb")
    assert (ext / "calkit.lua").stat().st_mtime_ns == mtime
    # In one, at its root, relative to wdir
    (tmp_path / "site" / "pages").mkdir(parents=True)
    (tmp_path / "site" / "_quarto.yml").write_text(
        "project:\n  type: website\n"
    )
    monkeypatch.chdir(tmp_path / "pub")
    calkit.quarto.write_components("site/pages/about.qmd", wdir=str(tmp_path))
    assert (
        tmp_path / "site" / "_extensions" / "calkit" / "calkit.lua"
    ).is_file()
    # A Quarto project at wdir counts, and the search stops there
    assert calkit.quarto.get_quarto_dir("site/a.qmd", str(tmp_path)) == "site"
    (tmp_path / "_quarto.yml").write_text("")
    assert calkit.quarto.get_quarto_dir("pub/a.qmd", str(tmp_path)) == ""
    assert calkit.quarto.get_quarto_dir("a.qmd", str(tmp_path / "pub")) == ""


@pytest.mark.skipif(shutil.which("quarto") is None, reason="needs Quarto")
@pytest.mark.parametrize("command", VALUE_COMMANDS)
def test_shortcode_matches_python(tmp_path, monkeypatch, command):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "r.json").write_text(
        json.dumps(
            {
                "rms": 0.123456,
                "n": 1234567,
                "neg": -0.000012345,
                "big": 1e16,
                "fifteen": 1e15,
                "whole": 19.0,
                "fit": {"coeffs": [1.5, 2, -3.25], "25": 0.0309},
                "flag": True,
                "name": "alpha",
                "negzero": -0.0,
                "x": 1234.5,
            }
        )
    )
    # With what Pandoc, which reads YAML for Quarto, sees differently, e.g.,
    # a document marker, or numbers it rewrites
    (tmp_path / "results" / "m.yaml").write_text(
        "\n---\nspeed: 3.25\ncount: 401\nnested:\n  list: [1, 2.5]\n"
        "trailing: 1.50\nsmall: 1.0e-3\nbig: .inf\nlabel: it's -- done...\n"
    )
    (tmp_path / "calkit.yaml").write_text(
        "\n# Project\nresults:\n  - name: metrics\n    path: results/m.yaml\n"
    )
    (tmp_path / "results" / "t.toml").write_text(
        "# Results\n"
        'title = "Run \\"A\\" \\u00e9"\n'
        "path = 'C:\\data'\n"
        "n = 1_234\n"
        "mask = 0xff\n"
        "rate = 6.5e-3  # per second\n"
        "whole = 2.0\n"
        "big = inf\n"
        "on = true\n"
        "fit.r2 = 0.987\n"
        'notes = """\nfirst\nsecond"""\n'
        "coeffs = [\n  1.5, # a\n  -2,\n]\n"
        "point = { x = 1, y.z = 2.5 }\n"
        "\n[case.'quoted']\nspeed = 12.25\n"
        "\n[[runs]]\nscore = 0.5\n"
        "\n[[runs]]\nscore = 0.75\n[runs.meta]\nseed = 7\n"
    )
    cases = [
        ("results/r.json", "rms", f)
        for f in ["", ".2f", ".3e", ".1%", "+.2f", "g", ".3g", "E", "%"]
    ]
    cases += [
        ("results/r.json", "n", f) for f in ["", ",", ",d", "_d", ",.2f"]
    ]
    cases += [
        ("results/r.json", key, "")
        for key in ["neg", "big", "fifteen", "whole", "flag", "negzero"]
    ]
    nb_values_path = tmp_path / ".calkit/notebooks/outputs/nbs/fit.ipynb"
    nb_values_path.mkdir(parents=True)
    (nb_values_path / "values.json").write_text(
        json.dumps({"k_25": 0.030912, "rates": {"25": 0.031}})
    )
    cases += [
        ("nbs/fit.ipynb", "k_25", ".3f"),
        ("nbs/fit.ipynb", "rates.25", ".1%"),
        ("results/r.json", "fit.coeffs.0", ".1%"),
        ("results/r.json", "fit.coeffs.-1", ""),
        ("results/r.json", "fit.25", ".3f"),
        ("results/r.json", "name", "s"),
        ("results/r.json", "x", "{value:.1f} m/s"),
        ("results/r.json", "x", "{0:.0f} and {value:,.2f}"),
        ("results/t.toml", "title", ""),
        ("results/t.toml", "path", ""),
        ("results/t.toml", "n", ",d"),
        ("results/t.toml", "mask", ""),
        ("results/t.toml", "rate", ".2e"),
        ("results/t.toml", "whole", ""),
        ("results/t.toml", "big", ""),
        ("results/t.toml", "on", ""),
        ("results/t.toml", "fit.r2", ".2f"),
        ("results/t.toml", "coeffs.1", ""),
        ("results/t.toml", "point.y.z", ""),
        ("results/t.toml", "case.quoted.speed", ".1f"),
        ("results/t.toml", "runs.1.score", ".0%"),
        ("results/t.toml", "runs.1.meta.seed", ""),
        ("metrics", "speed", ".1f"),
        ("metrics", "count", ",d"),
        ("metrics", "nested.list.1", ".2f"),
        ("metrics", "trailing", ""),
        ("metrics", "trailing", "+"),
        ("metrics", "small", ""),
        ("metrics", "big", ""),
        ("metrics", "label", ""),
    ]
    # In a folder below the project, since paths are relative to it
    (tmp_path / "docs").mkdir()
    lines = []
    for i, (source, key, fmt) in enumerate(cases):
        source = source if source == "metrics" else f"path={source}"
        fmt = f" format='{fmt}'" if fmt else ""
        lines.append(f"V{i}: {{{{< {command} {source} key={key}{fmt} >}}}}")
    lines.append(f"Gone: {{{{< {command} results/gone.json x >}}}}")
    (tmp_path / "docs" / "doc.qmd").write_text("\n\n".join(lines) + "\n")
    values = calkit.quarto.extract_values(
        "\n".join(lines[:-1]),
        "docs/doc.qmd",
        results={"metrics": "results/m.yaml"},
    )
    expected = calkit.quarto.check_values(values, "docs/doc.qmd")
    calkit.quarto.write_components("docs/doc.qmd")
    subprocess.check_call(
        ["quarto", "render", "doc.qmd", "--to", "plain"], cwd="docs"
    )
    got = (tmp_path / "docs" / "doc.txt").read_text().strip().split("\n\n")
    assert [line.split(": ", 1)[1].strip() for line in got[:-1]] == expected
    # A value that can't be read shows as missing
    assert got[-1].strip() == "Gone: ??"


def test_refvals(tmp_path):
    # A value quoted from a reference is read from the file Calkit writes
    # its reference's values to, by name, in document order
    from calkit.references.values import get_values_path, write_values_file

    path = get_values_path("liu.2025")

    text = (
        "Noise of {{< ckrefval liu.2025 noise-sigma .2f >}} "
        "[@liu.2025], and {{< ckvalue results/r.json rms >}}.\n"
        "Again {{< ckrefval liu.2025 noise-sigma format=.1f >}}.\n"
    )
    values = calkit.quarto.extract_values(text, "index.qmd")
    assert [(v.path, v.key, v.format, v.ref) for v in values] == [
        (path, "noise-sigma", ".2f", ("liu.2025", "noise-sigma")),
        ("results/r.json", "rms", None, None),
        (path, "noise-sigma", ".1f", ("liu.2025", "noise-sigma")),
    ]
    refvals = [v for v in values if v.ref]
    with pytest.raises(MarkdownParseError, match="records no value"):
        calkit.quarto.check_values(refvals, "index.qmd", wdir=str(tmp_path))
    write_values_file(
        {
            "references": [
                {
                    "path": "r.bib",
                    "values": {"liu.2025": {"noise-sigma": {"value": 0.1}}},
                }
            ]
        },
        wdir=str(tmp_path),
    )
    calkit.quarto.check_values(refvals, "index.qmd", wdir=str(tmp_path))
    missing = calkit.quarto.extract_values(
        "{{< ckrefval liu.2025 other >}}", "index.qmd"
    )
    with pytest.raises(
        MarkdownParseError,
        match="calkit.yaml records no value 'other' quoted from 'liu.2025'",
    ):
        calkit.quarto.check_values(missing, "index.qmd", wdir=str(tmp_path))
    with pytest.raises(MarkdownParseError, match="takes a citation key"):
        calkit.quarto.extract_values(
            "{{< ckrefval path=liu.2025 key=x >}}", "index.qmd"
        )


@pytest.mark.skipif(shutil.which("quarto") is None, reason="needs Quarto")
def test_refval_shortcode(tmp_path, monkeypatch):
    # Quarto renders the shortcode itself, finding the file of a
    # reference's values as Python names it, whatever the key, and a
    # missing one as ??
    from calkit.references.values import write_values_file

    monkeypatch.chdir(tmp_path)
    (tmp_path / "calkit.yaml").write_text("name: t\n")
    write_values_file(
        {
            "references": [
                {
                    "path": "r.bib",
                    "values": {
                        "liu.2025": {
                            "noise-sigma": {"value": 0.1},
                            "label": {"value": "α"},
                        },
                        "smith:2020/b+é": {"n": {"value": 7}},
                    },
                }
            ]
        },
        wdir=str(tmp_path),
    )
    (tmp_path / "index.qmd").write_text(
        "---\ntitle: T\n---\n\n"
        "A {{< ckrefval liu.2025 noise-sigma .2f >}} "
        "B {{< ckrefval liu.2025 label >}} "
        "C {{< ckrefval liu.2025 nope >}} "
        "D {{< ckrefval liu.2025 key=noise-sigma format=.1f >}} "
        "E {{< ckrefval smith:2020/b+é n >}}\n"
    )
    calkit.quarto.write_components("index.qmd", wdir=str(tmp_path))
    subprocess.check_call(
        ["quarto", "render", "index.qmd", "--to", "md"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    out = (tmp_path / "index.md").read_text()
    assert "A 0.10 B α C ?? D 0.1 E 7" in out
