"""Tests for ``calkit.quarto``."""

import json

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
    # Each is keyed by its arguments as written, which is what the shortcode
    # sees too
    assert values[2].id == "speed\tspeed\t{value:.1f} m/s"
    resolved = calkit.quarto.resolve_values(values, "doc.qmd")
    assert resolved == {
        "results.json\trms\t.2f": "0.12",
        "results.json\tfit.n\t": "401",
        "speed\tspeed\t{value:.1f} m/s": "3.2 m/s",
        "results.json\tfit.coeffs.0\t.1%": "150.0%",
    }
    # Mistakes name their line
    with pytest.raises(MarkdownParseError, match="names no key"):
        calkit.quarto.extract_values("\n{{< ckvalue a.json >}}", "doc.qmd")
    with pytest.raises(MarkdownParseError, match="doesn't exist"):
        calkit.quarto.resolve_values(
            calkit.quarto.extract_values(
                "{{< ckvalue gone.json x >}}", "doc.qmd"
            ),
            "doc.qmd",
        )
    with pytest.raises(MarkdownParseError, match="has no key 'nope'"):
        calkit.quarto.resolve_values(
            calkit.quarto.extract_values(
                "{{< ckvalue results.json nope >}}", "doc.qmd"
            ),
            "doc.qmd",
        )
    # The shortcode and each document's values are written beside it, and
    # left alone when already right
    (tmp_path / "pub").mkdir()
    calkit.quarto.write_components("pub/index.ipynb", {"a\tb\t": "1"})
    lua = tmp_path / "pub" / "_calkit" / "calkit.lua"
    values_path = tmp_path / "pub" / "_calkit" / "values" / "index.json"
    assert lua.read_text() == calkit.quarto.SHORTCODE_LUA
    assert json.loads(values_path.read_text()) == {"a\tb\t": "1"}
    assert calkit.quarto.get_values_path("pub/index.ipynb") == (
        "pub/_calkit/values/index.json"
    )
    mtime = lua.stat().st_mtime_ns
    calkit.quarto.write_components("pub/index.ipynb")
    assert lua.stat().st_mtime_ns == mtime
