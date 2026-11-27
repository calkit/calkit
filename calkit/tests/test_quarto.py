"""Tests for ``calkit.quarto``."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import calkit.dvc
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
    # A notebook stands for the values its cells save
    fit_values = calkit.quarto.extract_values(
        "{{< ckvalue nbs/fit.ipynb k_25 .3f >}}", "doc.qmd"
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


def test_provenance_records(tmp_path: Path) -> None:
    def get_text(node: dict | list) -> str:
        if isinstance(node, list):
            return "".join(get_text(n) for n in node)
        out = (
            str(node.get("value", "")) if node.get("type") != "mermaid" else ""
        )
        out += get_text(node.get("children") or [])
        if node.get("type") == "link":
            out += f"<{node['url']}>"
        return out + (
            "\n" if node.get("type") in ("paragraph", "tableRow") else ""
        )

    def get_graph(provenance: dict) -> str:
        return str(
            next(
                n["value"]
                for n in provenance["view"]
                if n["type"] == "mermaid"
            )
        )

    # Components are found outside code, named by their class, with a path
    # relative to the project, as values' are, and an id and options
    text = (
        '::: {.ckfigure src="figures/plot.svg" #fig-plot width="50%"}\n'
        "Caption\n:::\n"
        "```markdown\n::: {.ckfigure src=in-code.png}\n```\n"
        "::: {#tbl-data .cktable src='/data/clean.csv' rows=2} :::\n:::\n"
        "::: {.ckinclude src=notes.md provenance=false}\n:::\n"
        "> ::: {.ckfigure src=quoted.png}\n> :::\n"
        "::: {.callout-note src=other.png}\n:::\n"
        "::: {.ckfigure}\n:::\n"
    )
    components = calkit.quarto.extract_components(text)
    assert [
        (c.kind, c.src, c.path, c.label, c.line, c.rows, c.provenance)
        for c in components
    ] == [
        (
            "figure",
            "figures/plot.svg",
            "figures/plot.svg",
            "fig-plot",
            1,
            25,
            True,
        ),
        ("table", "/data/clean.csv", "data/clean.csv", "tbl-data", 7, 2, True),
        ("include", "notes.md", "notes.md", "", 9, 25, False),
        ("figure", "quoted.png", "quoted.png", "", 11, 25, True),
    ]
    assert calkit.quarto.has_components(text)
    assert not calkit.quarto.has_components("No components.")
    # A project: raw data cleaned, then plotted, and a notebook's value
    ck_info: dict = {
        "datasets": [
            {"path": "data/raw.csv", "created_by": {"name": "Jane Doe"}},
        ],
        "figures": [
            {
                "path": "figures/photo.png",
                "imported_from": {"url": "https://example.com/photo.png"},
            }
        ],
        "references": [
            {
                "path": "refs.bib",
                "values": {"liu2025": {"sigma": {"value": 0.1, "page": 4}}},
            }
        ],
        "environments": {"py": {"kind": "uv-venv", "path": "reqs.txt"}},
        "pipeline": {
            "stages": {
                "clean": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "scripts/clean.py",
                },
                "plot": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "scripts/plot.py",
                },
                "fit": {
                    "kind": "jupyter-notebook",
                    "environment": "py",
                    "notebook_path": "fit.ipynb",
                },
                "report": {
                    "kind": "quarto",
                    "target_path": "pub/report.qmd",
                    "environment": "_system",
                },
            }
        },
    }

    def get_entry(path: str) -> dict:
        return {"path": path, "hash": "md5", "md5": path + "-1"}

    values_path = ".calkit/notebooks/outputs/fit.ipynb/values.json"
    dvc_stages = {
        "clean": {
            "cmd": "python scripts/clean.py",
            "outs": [
                {"data/clean.csv": {"cache": False}},
                "results/big.parquet",
            ],
        },
        "plot": {
            "cmd": "python scripts/plot.py",
            "outs": [{"figures/plot.svg": {"cache": False}}],
        },
        "fit": {"cmd": "calkit nb execute fit.ipynb", "outs": [values_path]},
        "report": {"cmd": "calkit quarto render report.qmd", "wdir": "pub"},
    }
    lock_stages: dict[str, dict] = {
        "clean": {
            "cmd": "python scripts/clean.py",
            "deps": [get_entry("scripts/clean.py"), get_entry("data/raw.csv")],
            "outs": [
                get_entry("data/clean.csv"),
                get_entry("results/big.parquet"),
            ],
        },
        "plot": {
            "cmd": "python scripts/plot.py",
            "deps": [
                get_entry("scripts/plot.py"),
                get_entry("data/clean.csv"),
                get_entry("results/big.parquet"),
                get_entry(".calkit/env-locks/py.txt"),
            ],
            "outs": [get_entry("figures/plot.svg")],
        },
        "fit": {
            "cmd": "calkit nb execute fit.ipynb",
            "deps": [get_entry("fit.ipynb")],
            "outs": [get_entry(values_path)],
        },
        "report": {
            "cmd": "calkit quarto render report.qmd",
            "deps": [get_entry("report.qmd"), get_entry("own.png")],
            "outs": [get_entry("report.html"), get_entry("own.png")],
        },
    }
    stage_runs = {
        "plot": {
            "start_time": "2026-11-20T10:00:00",
            "git_rev": "abcdef123456",
            # Run before committing, as usual, which isn't a warning
            "git_dirty": True,
            "system": {"os": "Linux", "machine": "x86_64"},
            "dvc_lock_hash": calkit.dvc.stage_lock_hash(lock_stages["plot"]),
        },
        # A run that isn't the one dvc.lock records isn't shown
        "clean": {"start_time": "2026-11-19T10:00:00", "dvc_lock_hash": "x"},
    }
    files = {
        entry["path"]
        for stage in lock_stages.values()
        for entry in stage["deps"] + stage["outs"]
    } | {"figures/sketch.png", "figures/photo.png"}
    content = {
        "data/clean.csv": "x,y\n1,2\n3,4\n5,6\n",
        "figures/plot.svg": "<svg/>",
    }
    up_to_date = {
        "status": "up-to-date",
        "modified_command": False,
        "modified_inputs": [],
        "modified_outputs": [],
        "missing_outputs": [],
    }
    # Files in Git link to the repo's host, at the commit a run recorded
    in_git = {
        "scripts/clean.py",
        "scripts/plot.py",
        "data/raw.csv",
        "fit.ipynb",
    }

    def get_records(
        text: str,
        present: set[str] = files,
        statuses: dict[str, dict] | None = None,
        values: list | None = None,
        info: dict = ck_info,
        check: tuple[bool, str | None] = (False, None),
    ) -> dict:
        return calkit.quarto.get_provenance_records(
            calkit.quarto.extract_components(text),
            "pub/report.qmd",
            ck_info=info,
            dvc_yaml={"stages": dvc_stages},
            dvc_lock={"stages": lock_stages},
            stage_runs=stage_runs,
            get_stage_status=lambda name: {
                **up_to_date,
                **(statuses or {}).get(name, {}),
            },
            is_file=lambda p: p in present,
            is_dir=lambda p: False,
            listdir=lambda p: [],
            read_bytes=lambda p: content[p].encode(),
            values=values,
            get_file_url=lambda p, sha: (
                f"https://host.example/{sha or 'HEAD'}/{p}"
                if p in in_git
                else None
            ),
            check_reference_value=lambda key, name: check,
        )

    text = (
        "::: {.ckfigure src=figures/plot.svg #fig-plot}\n:::\n"
        "::: {.cktable src=data/clean.csv #tbl-data rows=2}\n:::\n"
        "::: {.ckfigure src=figures/photo.png}\n:::\n"
        "::: {.ckfigure src=figures/sketch.png}\n:::\n"
        "::: {.ckfigure src=figures/gone.png}\n:::\n"
        "::: {.ckfigure src=own.png}\n:::\n"
        "::: {.ckfigure src=figures/plot.svg provenance=false}\n:::\n"
    )
    records = get_records(text)["components"]
    assert list(records) == [
        "figures/plot.svg",
        "data/clean.csv",
        "figures/photo.png",
        "figures/sketch.png",
        "figures/gone.png",
        "own.png",
    ]
    plot = records["figures/plot.svg"]
    # Referred to from where the document is
    # With its file's SHA-1, so what shows it can tell it changed since
    assert (plot["kind"], plot["url"], plot["sha1"]) == (
        "figure",
        "../figures/plot.svg",
        hashlib.sha1(b"<svg/>").hexdigest(),
    )
    provenance = plot["provenance"]
    # Quiet while it's up to date, with nothing for formats that can't
    # expand
    assert provenance["state"] == "ok"
    assert get_text(provenance["summary"]) == "Provenance"
    assert provenance["line"] is None
    view = get_text(provenance["view"])
    # The whole chain, upstream first, with each stage's kind, environment,
    # script, last run, and every input, with where each came from
    assert view.index("Stage clean") < view.index("Stage plot")
    assert "Stage clean (python-script), environment py (uv-venv)\n" in view
    assert (
        "Runs scripts/clean.py<https://host.example/HEAD/scripts/clean.py>\n"
        in view
    )
    assert "Last run not recorded for its current outputs\n" in view
    assert (
        "Runs scripts/plot.py<https://host.example/abcdef123456/scripts/plot.py>\n"
        in view
    )
    assert "Last run 2026-11-20, Linux x86_64, after commit abcdef1\n" in view
    assert "uncommitted" not in view
    assert (
        "data/raw.csv<https://host.example/HEAD/data/raw.csv>Created by Jane Doe"
        "✅ unchanged\n" in view
    )
    # What's shown in the document links there, and what DVC keeps, by hash
    assert "data/clean.csv<#tbl-data>stage clean✅ unchanged\n" in view
    assert (
        "results/big.parquet (DVC md5 results)stage clean✅ unchanged\n"
        in view
    )
    assert "Makes figures/plot.svg<#fig-plot>\n" in view
    # Without Calkit's bookkeeping, e.g., an environment's lock
    assert ".calkit" not in view
    # The graph is only of what it's made from
    graph = get_graph(provenance)
    assert '[["clean"]]' in graph and '[["plot"]]' in graph
    assert "fit" not in graph and "report" not in graph
    assert '("figures/plot.svg"):::ok' in graph
    assert "class f" in graph and "target" in graph
    # A table's rows are read when the document renders, so they're current
    table = records["data/clean.csv"]
    assert table["kind"] == "table" and "body" not in table
    assert (
        table["sha1"]
        == hashlib.sha1(content["data/clean.csv"].encode()).hexdigest()
    )
    assert "plot" not in get_graph(table["provenance"])
    # A file no stage makes, in Git, says so
    assert (
        "scripts/clean.py<https://host.example/HEAD/scripts/clean.py>in Git"
        in view
    )
    # Something imported says from where, and something nothing accounts
    # for says so while collapsed, with how to fix it
    photo = records["figures/photo.png"]["provenance"]
    assert photo["state"] == "ok"
    assert "https://example.com/photo.png" in json.dumps(photo)
    sketch = records["figures/sketch.png"]["provenance"]
    assert sketch["state"] == "incomplete"
    assert get_text(sketch["summary"]) == (
        "⚠️ Incomplete provenance: origin not defined for figures/sketch.png"
    )
    assert get_text(sketch["line"]) == (
        "Figure has incomplete provenance: origin not defined for "
        "figures/sketch.png"
    )
    assert "To fix figures/sketch.png: it's exported from something else" in (
        get_text(sketch["view"])
    )
    assert get_text(records["figures/gone.png"]["provenance"]["summary"]) == (
        "⛔ Missing"
    )
    # What the document makes itself can't be said to be up to date
    assert get_text(records["own.png"]["provenance"]["summary"]) == (
        "Provenance: made by this document"
    )
    # Turned off for one, which still counts, or for the project, though
    # it's worked out if it's shown elsewhere
    off = get_records(
        "::: {.ckfigure src=figures/plot.svg provenance=false}\n:::\n"
    )
    assert off["components"]["figures/plot.svg"]["provenance"] is None
    off = get_records(
        "::: {.ckfigure src=figures/plot.svg provenance=false}\n:::\n"
        "::: {.ckfigure src=figures/plot.svg}\n:::\n"
    )
    assert off["components"]["figures/plot.svg"]["provenance"] is not None
    off = get_records(text, info={**ck_info, "show_provenance": False})
    assert all(r["provenance"] is None for r in off["components"].values())
    # An edited script makes what it made out of date, and what's made from
    # that wait on it, said while collapsed
    stale = {"status": "stale", "modified_inputs": ["scripts/clean.py"]}
    records = get_records(text, statuses={"clean": stale})["components"]
    provenance = records["figures/plot.svg"]["provenance"]
    assert provenance["state"] == "stale"
    assert get_text(provenance["summary"]) == (
        "⚠️ Out of date: waiting on data/clean.csv, results/big.parquet"
    )
    assert get_text(provenance["line"]) == (
        "Figure out of date: waiting on data/clean.csv, results/big.parquet"
    )
    view = get_text(provenance["view"])
    assert (
        "scripts/clean.py<https://host.example/HEAD/scripts/clean.py>✅"
        not in view
    )
    assert "⚠️ modified" in view
    assert "data/clean.csv<#tbl-data>stage clean⚠️ out of date\n" in view
    assert "To update: calkit run\n" in view
    assert '("data/clean.csv"):::stale' in get_graph(provenance)
    assert get_text(records["data/clean.csv"]["provenance"]["summary"]) == (
        "⚠️ Out of date: scripts/clean.py modified"
    )
    # As do an output edited by hand, a deleted input, and a stage that
    # always runs, which doesn't hold up what's made from it
    cases: list[tuple[set[str], dict, str]] = [
        (
            files,
            {"plot": {"status": "stale", "modified_outputs": ["figures"]}},
            "⚠️ Out of date: modified outside pipeline",
        ),
        (
            files - {"data/clean.csv"},
            {
                "plot": {
                    "status": "stale",
                    "modified_inputs": ["data/clean.csv"],
                },
                "clean": {
                    "status": "stale",
                    "missing_outputs": ["data/clean.csv"],
                },
            },
            "⚠️ Out of date: data/clean.csv missing",
        ),
        (files, {"clean": {"status": "always-run"}}, "Provenance"),
    ]
    for present, statuses, summary in cases:
        records = get_records(text, present, statuses)["components"]
        provenance = records["figures/plot.svg"]["provenance"]
        assert get_text(provenance["summary"]) == summary
    # Data DVC tracks says so where it's read, and when it's shown
    dvc_stale = {
        "data/raw.csv.dvc": {"status": "stale"},
        "figures/sketch.png.dvc": {"status": "stale"},
    }
    records = get_records(
        text,
        files | {"data/raw.csv.dvc", "figures/sketch.png.dvc"},
        dvc_stale,
    )["components"]
    assert "Created by Jane Doe⚠️ modified since added to DVC\n" in get_text(
        records["figures/plot.svg"]["provenance"]["view"]
    )
    assert get_text(
        records["figures/sketch.png"]["provenance"]["summary"]
    ) == ("⚠️ Out of date: modified since added to DVC")
    # Raw data with no origin is a gap in what's made from it
    no_origin = {**ck_info, "datasets": []}
    records = get_records(text, info=no_origin)["components"]
    assert get_text(records["data/clean.csv"]["provenance"]["summary"]) == (
        "⚠️ Incomplete provenance: origin not defined for data/raw.csv"
    )
    assert (
        "data/raw.csv<https://host.example/HEAD/data/raw.csv>❔ origin not defined"
        in (get_text(records["data/clean.csv"]["provenance"]["view"]))
    )
    # Values: from a results file, from a notebook's cell, and quoted from a
    # reference, keyed as what shows them looks them up
    values = calkit.quarto.extract_values(
        "{{< ckvalue results/big.parquet n >}} "
        "{{< ckvalue fit.ipynb k_25 .3f >}} "
        "{{< ckrefval liu2025 sigma >}} {{< ckrefval liu2025 other >}} "
        "{{< ckvalue fit.ipynb k_35 provenance=false >}}",
        "pub/report.qmd",
    )
    assert [v.provenance for v in values] == [True, True, True, True, False]
    records = get_records("", values=values)["values"]
    assert list(records) == [
        "results/big.parquet:n",
        f"{values_path}:k_25",
        "ref:liu2025:sigma",
        "ref:liu2025:other",
        f"{values_path}:k_35",
    ]
    assert records[f"{values_path}:k_35"]["provenance"] is None
    result = records["results/big.parquet:n"]["provenance"]
    assert get_text(result["view"]).startswith(
        "n in results/big.parquet (DVC md5 results)\n"
    )
    assert '[["clean"]]' in get_graph(result)
    nb_value = records[f"{values_path}:k_25"]["provenance"]
    assert get_text(nb_value["view"]).startswith(
        "k_25, saved from a cell of fit.ipynb<https://host.example/HEAD/fit.ipynb>\n"
    )
    assert "Stage fit (jupyter-notebook)" in get_text(nb_value["view"])
    stale_values = get_records("", statuses={"clean": stale}, values=values)[
        "values"
    ]
    assert get_text(
        stale_values["results/big.parquet:n"]["provenance"]["summary"]
    ) == ("⚠️ Out of date: scripts/clean.py modified")
    # One from a reference says what it's recorded as, and whether it
    # matched the reference's PDF, rather than a pipeline
    reference = records["ref:liu2025:sigma"]["provenance"]
    assert reference["state"] == "ok"
    assert get_text(reference["view"]).startswith(
        "sigma, quoted from reference liu2025 in refs.bib\n"
        "Recorded as 0.1, on page 4\n"
        "Not checked against its PDF"
    )
    assert not any(n["type"] == "mermaid" for n in reference["view"])
    for check, state, summary in [
        ((True, None), "ok", "Provenance"),
        (
            (True, "0.1 isn't on page 4"),
            "stale",
            "⚠️ Doesn't match its reference: 0.1 isn't on page 4",
        ),
    ]:
        checked = get_records("", values=values, check=check)["values"]
        reference = checked["ref:liu2025:sigma"]["provenance"]
        assert (reference["state"], get_text(reference["summary"])) == (
            state,
            summary,
        )
    assert get_text(records["ref:liu2025:other"]["provenance"]["summary"]) == (
        "⛔ Not recorded for its reference"
    )
    # Written where what renders it reads it
    assert calkit.quarto.get_provenance_path("pub/report.qmd") == (
        ".calkit/local/provenance/pub/report.qmd.json"
    )


def test_stage_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def dvc(*args: str) -> str:
        return subprocess.check_output(
            [sys.executable, "-m", "dvc", *args], text=True, cwd=tmp_path
        )

    def get_statuses() -> dict[str, dict]:
        repo = calkit.dvc.get_dvc_repo(str(tmp_path))
        return {
            stage.addressing: calkit.quarto.get_stage_status(stage)
            for stage in repo.index.stages
        }

    def write_pipeline(make: dict, each_cmd: str) -> None:
        with open(tmp_path / "dvc.yaml", "w") as f:
            calkit.ryaml.dump(
                {
                    "stages": {
                        "make": {"cmd": "cp in.txt out.txt", **make},
                        "each": {
                            "matrix": {"n": ["x", "y"]},
                            "cmd": each_cmd,
                            "outs": ["${item.n}.txt"],
                        },
                    }
                },
                f,
            )

    monkeypatch.chdir(tmp_path)
    dvc("init", "--no-scm")
    (tmp_path / "in.txt").write_text("in\n")
    (tmp_path / "extra.txt").write_text("extra\n")
    make = {"deps": ["in.txt"], "outs": ["out.txt"]}
    each_cmd = "echo ${item.n} > ${item.n}.txt"
    write_pipeline(make, each_cmd)
    dvc("repro")
    assert {n: s["status"] for n, s in get_statuses().items()} == {
        "make": "up-to-date",
        "each@x": "up-to-date",
        "each@y": "up-to-date",
    }
    # It says what DVC does, for what's read or made being added or removed,
    # which DVC doesn't count for an output, and an iterated stage's command
    # changing, without the repo lock
    cases: list[tuple[dict, str, set[str], dict]] = [
        (
            {**make, "deps": ["in.txt", "extra.txt"]},
            each_cmd,
            {"make"},
            {"modified_inputs": ["extra.txt"]},
        ),
        (
            {**make, "outs": ["out.txt", "out2.txt"]},
            each_cmd,
            {"make"},
            {"missing_outputs": ["out2.txt"]},
        ),
        ({**make, "outs": []}, each_cmd, set(), {}),
        (
            make,
            "echo ${item.n}! > ${item.n}.txt",
            {"each@x", "each@y"},
            {"modified_command": True},
        ),
    ]
    for case_make, case_cmd, names, expected in cases:
        write_pipeline(case_make, case_cmd)
        stale = set(json.loads(dvc("status", "--json")))
        got = get_statuses()
        assert {n for n, s in got.items() if s["status"] == "stale"} == stale
        assert stale == names, (case_make, case_cmd)
        for name in names:
            assert {k: got[name][k] for k in expected} == expected
    # One that hasn't changed is up to date again
    write_pipeline(make, each_cmd)
    assert all(s["status"] == "up-to-date" for s in get_statuses().values())
    # Panels are written from DVC's status, rendered from a stage's working
    # directory too, which DVC would otherwise name stages relative to
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path / "sub")
    components = calkit.quarto.extract_components(
        "::: {.ckinclude src=out.txt}\n:::\n"
    )
    (tmp_path / "doc.qmd").write_text("")
    for content, summary in [
        ("in\n", "Provenance"),
        ("changed\n", "⚠️ Out of date: in.txt modified"),
    ]:
        (tmp_path / "in.txt").write_text(content)
        record_path = calkit.quarto.write_provenance(
            components, "doc.qmd", {}, wdir=str(tmp_path)
        )
        record = json.loads((tmp_path / record_path).read_text())
        provenance = record["components"]["out.txt"]["provenance"]
        assert provenance["summary"][0]["value"] == summary
    assert os.getcwd() == str(tmp_path / "sub")


def test_filter_problem(tmp_path: Path) -> None:
    # Whether a document embeds what its HTML loads is read the way Quarto
    # reads it, the nearest setting winning
    (tmp_path / "_quarto.yml").write_text(
        "format:\n  html:\n    embed-resources: true\n"
    )
    for text, embeds in [
        ("Text\n", True),
        ("---\nembed-resources: false\n---\n", False),
        ("---\nformat:\n  html:\n    self-contained: false\n---\n", False),
    ]:
        assert (
            calkit.quarto.embeds_resources(text, "doc.qmd", wdir=str(tmp_path))
            == embeds
        ), text
    (tmp_path / "_quarto.yml").unlink()
    assert not calkit.quarto.embeds_resources(
        "Text\n", "doc.qmd", wdir=str(tmp_path)
    )
    listed = (
        "---\ntitle: T\nfilters:\n  - at: pre-ast\n    path: calkit\n---\n"
    )
    assert calkit.quarto.get_filter_problem(listed, "doc.qmd") is None
    # Not listed, or listed to run after Quarto numbers figures, says what
    # to add
    for text, match in [
        ("---\ntitle: T\n---\n", "need Calkit's filter listed,"),
        ("No front matter\n", "need Calkit's filter listed,"),
        ("---\nfilters: [calkit]\n---\n", "listed to run at pre-ast"),
    ]:
        problem = calkit.quarto.get_filter_problem(text, "doc.qmd")
        assert problem is not None and match in problem
        assert calkit.quarto.FILTER_CONFIG in problem
    # One listed for a format runs for that format
    html_only = (
        "---\nformat:\n  html+raw:\n    filters:\n"
        "      - {at: pre-ast, path: calkit}\n---\n"
    )
    for to, ok in [(None, True), ("html", True), ("pdf", False)]:
        problem = calkit.quarto.get_filter_problem(html_only, "doc.qmd", to=to)
        assert (problem is None) == ok, to
    # The Quarto project's config, or a folder's metadata, can list it
    (tmp_path / "pub" / "pages").mkdir(parents=True)
    (tmp_path / "pub" / "_quarto.yml").write_text(
        "project:\n  type: website\nformat:\n  html:\n    filters:\n"
        "      - {at: pre-ast, path: calkit}\n"
    )
    assert (
        calkit.quarto.get_filter_problem(
            "Text\n", "pub/pages/doc.qmd", wdir=str(tmp_path)
        )
        is None
    )
    (tmp_path / "pub" / "_quarto.yml").write_text(
        "project:\n  type: default\n"
    )
    assert calkit.quarto.get_filter_problem(
        "Text\n", "pub/pages/doc.qmd", wdir=str(tmp_path)
    )
    (tmp_path / "pub" / "pages" / "_metadata.yml").write_text(listed[4:-4])
    assert (
        calkit.quarto.get_filter_problem(
            "Text\n", "pub/pages/doc.qmd", wdir=str(tmp_path)
        )
        is None
    )


@pytest.mark.skipif(shutil.which("quarto") is None, reason="needs Quarto")
def test_provenance_filter(tmp_path: Path) -> None:
    import nbformat

    def render(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["calkit", "quarto", "render", "-e", "_system", *args],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

    def read_html() -> str:
        html = (tmp_path / "report.html").read_text()
        return html.replace("\xa0", " ").replace("&nbsp;", " ")

    def get_summaries(html: str) -> list[tuple[str, str]]:
        found = re.findall(
            r'<details class="ck-provenance ([^"]*)"><summary[^>]*>(.*?)'
            r"</summary>",
            html,
            re.S,
        )
        return [(c, re.sub(r"\s+", " ", t)) for c, t in found]

    def get_values(html: str) -> list[tuple[str, str, str]]:
        return re.findall(
            r'<span class="ck-value ([^"]*)" data-ck-popover="([^"]*)"'
            r"[^>]*>([^<]*)",
            html,
        )

    subprocess.check_call(["calkit", "init"], cwd=tmp_path)
    subprocess.check_call(
        ["git", "remote", "add", "origin", "git@github.com:example/proj.git"],
        cwd=tmp_path,
    )
    for folder in ["scripts", "data", "figures", "results"]:
        (tmp_path / folder).mkdir()
    (tmp_path / "data" / "raw.csv").write_text("x,y\n1,2\n3,4\n")
    # With a byte order mark and something that isn't UTF-8
    (tmp_path / "data" / "bom.csv").write_bytes(b"\xef\xbb\xbfp,q\n\xff,2\n")
    (tmp_path / "scripts" / "clean.py").write_text(
        "import json, shutil\n"
        "shutil.copy('data/raw.csv', 'data/clean.csv')\n"
        "json.dump({'fit': {'slope': 0.123456}}, open('results/fit.json', 'w'))\n"
    )
    (tmp_path / "scripts" / "plot.py").write_text(
        "open('figures/plot.svg', 'w').write(\n"
        '    \'<svg xmlns="http://www.w3.org/2000/svg" width="10" '
        'height="10"/>\'\n)\n'
    )
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell("k_25 = 0.0309")]
    nbformat.write(nb, str(tmp_path / "fit.ipynb"))
    subprocess.check_call(
        ["calkit", "new", "uv-venv", "-n", "py", "ipykernel"], cwd=tmp_path
    )
    stage = {"kind": "python-script", "environment": "_system"}
    ck_info = calkit.load_calkit_info(wdir=str(tmp_path))
    ck_info.update(
        {
            "requirements": ["quarto"],
            "datasets": [
                {"path": "data/raw.csv", "created_by": {"name": "Jo"}},
                {"path": "data/bom.csv", "created_by": {"name": "Jo"}},
            ],
            "references": [
                {
                    "path": "refs.bib",
                    "values": {
                        "liu2025": {"sigma": {"value": 0.1, "page": 4}}
                    },
                }
            ],
        }
    )
    ck_info["pipeline"] = {
        "stages": {
            "clean": {
                **stage,
                "script_path": "scripts/clean.py",
                "inputs": ["data/raw.csv"],
                "outputs": [
                    {"path": "data/clean.csv", "storage": "git"},
                    {"path": "results/fit.json", "storage": "git"},
                ],
            },
            "plot": {
                **stage,
                "script_path": "scripts/plot.py",
                "inputs": ["data/clean.csv"],
                "outputs": [{"path": "figures/plot.svg", "storage": "git"}],
            },
            "fit": {
                "kind": "jupyter-notebook",
                "notebook_path": "fit.ipynb",
                "environment": "py",
                "html_storage": None,
                "cell_outputs": [
                    {
                        "kind": "value",
                        "cell_id": nb.cells[0].id,
                        "variable_name": "k_25",
                    }
                ],
            },
            "report": {
                "kind": "quarto",
                "target_path": "report.qmd",
                "environment": "_system",
                "outputs": ["report.html"],
            },
        }
    }
    with open(tmp_path / "calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    (tmp_path / "refs.bib").write_text(
        "@article{liu2025, title={T}, author={Liu}, year={2025}}\n"
    )
    body = (
        '::: {.ckfigure src="figures/plot.svg" #fig-plot width="50%" '
        ".lightbox}\nThe plot.\n:::\n\n"
        "As written, {{< ckvalue ./results/fit.json fit.slope .2f >}}. "
        "The slope is {{< ckvalue results/fit.json fit.slope .3f >}}, k is "
        "{{< ckvalue fit.ipynb k_25 .3f >}}, sigma is "
        "{{< ckrefval liu2025 sigma >}}, and not shown, "
        "{{< ckvalue results/fit.json fit.slope .1f provenance=false >}}; "
        "see @fig-plot and @tbl-data.\n\n"
        "::: {.cktable src=data/clean.csv #tbl-data rows=1}\nThe data.\n:::\n\n"
        "::: {.cktable src=data/clean.csv #tbl-list}\n- A list caption\n:::\n\n"
        "## Slope {{< ckvalue results/fit.json fit.slope .2f >}}\n\n"
        "::: {.cktable src=data/bom.csv #tbl-bom provenance=false} :::\n"
        "BOM.\n:::\n\n"
        "::: {.ckprovenance}\n:::\n"
    )
    # Without the filter listed, it fails before rendering, saying what to
    # add
    (tmp_path / "report.qmd").write_text(
        "---\ntitle: Report\n---\n\n::: {.ckfigure src=figures/plot.svg}\n:::\n"
    )
    res = render("report.qmd")
    assert res.returncode != 0
    assert calkit.quarto.FILTER_CONFIG in res.stdout + res.stderr
    (tmp_path / "report.qmd").write_text(
        "---\ntitle: Report\n" + calkit.quarto.FILTER_CONFIG + "---\n\n" + body
    )
    # In Git, so the scripts link to the repo's host
    subprocess.check_call(["git", "add", "-A"], cwd=tmp_path)
    subprocess.check_call(
        [
            "git",
            "-c",
            "user.name=T",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-qm",
            "Add project",
        ],
        cwd=tmp_path,
    )
    # On the host, as far as this clone knows
    subprocess.check_call(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path
    )
    subprocess.check_call(["calkit", "run"], cwd=tmp_path)
    # What it shows is what it's made from, even without its provenance
    with open(tmp_path / "dvc.yaml") as f:
        deps = calkit.ryaml.load(f)["stages"]["report"]["deps"]
    assert {
        "figures/plot.svg",
        "data/clean.csv",
        "data/bom.csv",
        "results/fit.json",
    } <= set(deps)
    html = read_html()
    # Numbered and cross-referenced by Quarto, so the filter ran first
    assert "Figure 1: The plot." in html
    assert "Table 1: The data." in html
    assert "Table 2: A list caption" in html
    assert "Table 3: BOM." in html
    assert 'href="#fig-plot" class="quarto-xref">Figure 1' in html
    # Once each, on the float Quarto makes
    assert html.count('id="tbl-data"') == 1
    # A table's rows are read as it renders, as far as it says
    assert "First row of data/clean.csv" in html
    # Mermaid is only loaded when a view opens
    assert "mermaid.min.js" not in html
    libs = tmp_path / "report_files" / "libs" / "quarto-contrib"
    assert (libs / "calkit-provenance" / "mermaid.min.js").is_file()
    # Stages run with the document say when, before it's recorded
    assert "Last run not recorded" not in html
    assert "Last run 20" in html
    # Each component's provenance is collapsed under it, quietly
    assert get_summaries(html) == [("ck-ok", "Provenance")] * 3
    # Expanded, it's how it came to be, with a graph of only what it's
    # made from, and links to the repo's host and the document
    figure_view = html.split('<details class="ck-provenance ck-ok">')[1]
    figure_view = figure_view.split("</details>")[0]
    assert '<pre class="ck-mermaid">' in figure_view
    assert '[["clean"]]' in figure_view
    assert "fit" not in figure_view.split("</pre>")[0]
    assert (
        'href="https://github.com/example/proj/blob/' in figure_view
        and "/scripts/plot.py" in figure_view
    )
    assert '<a href="#tbl-data"><code>data/clean.csv</code></a>' in figure_view
    # Values read as text, opening where they came from, except one with
    # it turned off, and one from a reference says what it's recorded as
    values = get_values(html)
    assert [(c, v) for c, _, v in values][:4] == [
        ("ck-ok", "0.12"),
        ("ck-ok", "0.123"),
        ("ck-ok", "0.031"),
        ("ck-ok", "0.1"),
    ]
    # Marked as text, which provenance.js makes buttons except where they
    # can't go, e.g., a heading, so nothing's nested in a link
    assert "<button" not in html
    assert 'data-ck-label="Where 0.123 came from"' in html
    assert "and not shown, 0.1;" in html
    popovers = {}
    for _, id_, _ in values:
        popover = html.split(f'<div id="{id_}" popover="" class="ck-popover"')
        popovers[id_] = re.sub(
            r"\s+", " ", popover[1].split("</div>\n</div>")[0]
        )
    assert "saved from a cell of" in popovers[values[2][1]]
    assert (
        "<strong>Stage</strong> <code>fit</code> (jupyter-notebook)"
        in popovers[values[2][1]]
    )
    assert (
        "quoted from reference <code>liu2025</code>" in popovers[values[3][1]]
    )
    assert "Recorded as 0.1, on page 4" in popovers[values[3][1]]
    # With the figure's own options, e.g., a lightbox
    assert "lightbox" in html
    # Other formats show the value, and nothing while it's up to date
    res = render("report.qmd", "--to", "gfm", "--", "-o", "report.md")
    assert res.returncode == 0, res.stdout + res.stderr
    md = (tmp_path / "report.md").read_text().replace("\xa0", " ")
    assert "The slope is 0.123, k is 0.031, sigma is 0.1" in md
    assert "Provenance" not in md and "out of date" not in md
    assert "| p   | q   |" in md
    assert "Use .ckfigure, .cktable, or .ckinclude" in md
    # An edited script makes what's made from it out of date, said while
    # collapsed, inline for a value, and in a line in other formats
    with open(tmp_path / "scripts" / "clean.py", "a") as f:
        f.write("# Edited\n")
    res = render("report.qmd")
    assert res.returncode == 0, res.stdout + res.stderr
    html = read_html()
    assert get_summaries(html) == [
        ("ck-stale", "⚠️ Out of date: waiting on data/clean.csv"),
        ("ck-stale", "⚠️ Out of date: scripts/clean.py modified"),
        ("ck-stale", "⚠️ Out of date: scripts/clean.py modified"),
    ]
    assert [c for c, _, _ in get_values(html)][1] == "ck-stale"
    assert '0.123<span class="ck-flag" aria-hidden="true">⚠</span>' in html
    res = render("report.qmd", "--to", "gfm", "--", "-o", "report.md")
    md = (tmp_path / "report.md").read_text().replace("\xa0", " ")
    assert "*Figure out of date: waiting on data/clean.csv*" in md
    # Rendered without Calkit after a file it shows changed, it shows the
    # file as it is, saying it changed since
    res = render("report.qmd")
    (tmp_path / "data" / "clean.csv").write_text("x,y\n7,8\n")
    subprocess.check_call(["quarto", "render", "report.qmd"], cwd=tmp_path)
    html = read_html()
    assert get_summaries(html)[1] == (
        "ck-stale ck-outdated",
        "⚠️ Out of date: scripts/clean.py modified · recorded before "
        "data/clean.csv changed",
    )
    assert "<td>7</td>" in html
    # Rendered without Calkit after the document changed, it says so
    record_path = tmp_path / calkit.quarto.get_provenance_path("report.qmd")
    record = json.loads(record_path.read_text())
    assert (
        record["source_sha1"]
        == hashlib.sha1((tmp_path / "report.qmd").read_bytes()).hexdigest()
    )
    with open(tmp_path / "report.qmd", "a") as f:
        f.write("\nMore text.\n")
    subprocess.check_call(["quarto", "render", "report.qmd"], cwd=tmp_path)
    html = read_html()
    assert all("ck-outdated" in c for c, _ in get_summaries(html))
    assert html.count("recorded before this document changed") >= 2
    # With nothing recorded, it says so, keeping the table's caption and id
    record_path.unlink()
    subprocess.check_call(["quarto", "render", "report.qmd"], cwd=tmp_path)
    html = read_html()
    assert (
        get_summaries(html) == [("ck-missing", "⚠️ No provenance recorded")] * 3
    )
    assert 'href="#tbl-data" class="quarto-xref">Table 1' in html
    assert "Table 1: The data." in html
    # With its rows, which are read from the file
    assert "<td>7</td>" in html
