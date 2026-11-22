"""Tests for ``calkit.quarto``."""

import json
import shutil
import subprocess

import pytest

import calkit.quarto
from calkit.markdown import MarkdownParseError


def test_values(tmp_path, monkeypatch):
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
    (tmp_path / "doc.ipynb").write_text(json.dumps(nb))
    text = calkit.quarto.read_document_text("doc.ipynb")
    assert text == "The RMS is\n{{< \n{{< ckvalue results.json rms >}}"
    assert calkit.quarto.read_document_text("missing.qmd") is None
    # Arguments read like the Markdown marker's, positionally or by name,
    # with a declared result's name standing for its path
    text = (
        "RMS {{< ckvalue results.json rms .2f >}} over "
        "{{< ckvalue key=fit.n path=results.json >}} samples\n"
        "at {{< ckvalue speed key=speed format='{value:.1f} m/s' >}}; "
        "{{</* ckvalue escaped.json x */>}}\n"
        "{{< ckvalue results.json fit.coeffs.0 .1% >}}\n"
    )
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
    # As are what the shortcode can't read or format the way Python does
    (tmp_path / "metrics.toml").write_text("speed = 3.25\n")
    for text, match in [
        ("{{< ckvalue metrics.toml speed >}}", "reads JSON and YAML"),
        ("{{< ckvalue results.json rms ' .2f' >}}", "can't format"),
        ("{{< ckvalue results.json rms 8.2f >}}", "can't format"),
        ("{{< ckvalue results.json rms '{x:.2f}' >}}", "can't format"),
        ("{{< ckvalue results.json rms d >}}", "Can't format 'rms'"),
    ]:
        with pytest.raises(MarkdownParseError, match=match):
            calkit.quarto.check_values(
                calkit.quarto.extract_values(text, "doc.qmd"), "doc.qmd"
            )
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
def test_shortcode_matches_python(tmp_path, monkeypatch):
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
    (tmp_path / "results" / "m.yaml").write_text(
        "speed: 3.25\ncount: 401\nnested:\n  list: [1, 2.5]\n"
    )
    (tmp_path / "calkit.yaml").write_text(
        "results:\n  - name: metrics\n    path: results/m.yaml\n"
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
    cases += [
        ("results/r.json", "fit.coeffs.0", ".1%"),
        ("results/r.json", "fit.coeffs.-1", ""),
        ("results/r.json", "fit.25", ".3f"),
        ("results/r.json", "name", "s"),
        ("results/r.json", "x", "{value:.1f} m/s"),
        ("results/r.json", "x", "{0:.0f} and {value:,.2f}"),
        ("metrics", "speed", ".1f"),
        ("metrics", "count", ",d"),
        ("metrics", "nested.list.1", ".2f"),
    ]
    # In a folder below the project, since paths are relative to it
    (tmp_path / "docs").mkdir()
    lines = []
    for i, (source, key, fmt) in enumerate(cases):
        source = source if source == "metrics" else f"path={source}"
        fmt = f" format='{fmt}'" if fmt else ""
        lines.append(f"V{i}: {{{{< ckvalue {source} key={key}{fmt} >}}}}")
    lines.append("Gone: {{< ckvalue results/gone.json x >}}")
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
